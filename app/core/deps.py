from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings
from redis.asyncio import Redis
from typing import Generator, AsyncGenerator, Callable
from app.core.security import decode_access_token, TokenDecodeError, TokenExpiredError
from app.db.models.user import User, RoleEnum
from app.services.users import ensure_user_active

# --- DB ---
DB_URL = settings.database_url
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Redis (optional) ---
async def get_redis() -> AsyncGenerator[Redis | None, None]:
    if not settings.REDIS_URL:
        yield None
        return

    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        await client.ping()
    except Exception:
        await client.close()
        yield None
        return

    try:
        yield client
    finally:
        await client.close()


# --- Auth / Permissions ---
bearer_scheme = HTTPBearer(auto_error=False)

ROLE_SCORE: dict[RoleEnum, int] = {
    RoleEnum.user: 0,
    RoleEnum.business: 1,
    RoleEnum.admin: 2,
    RoleEnum.super_admin: 3,
    RoleEnum.system_admin: 4,
}

SESSION_FIELD_BY_CLIENT = {
    "app": "app_session_id",
    "web": "web_session_id",
}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证信息")

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    except TokenDecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证，请重新登录")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="凭证缺少用户信息")

    user = db.get(User, user_id)
    if not ensure_user_active(db, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")

    client_type = payload.get("client")
    sid = payload.get("sid")
    session_field = SESSION_FIELD_BY_CLIENT.get(client_type)
    if not session_field or not sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    expected_sid = getattr(user, session_field, None)
    if not expected_sid or expected_sid != sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已在其他设备登录，请重新登录")

    return user


def role_at_least(user_role: RoleEnum, required: RoleEnum) -> bool:
    return ROLE_SCORE.get(user_role, -1) >= ROLE_SCORE.get(required, -1)


def require_min_role(required_role: RoleEnum) -> Callable[..., User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if role_at_least(current_user.role, required_role):
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return dependency


def require_roles(*roles: RoleEnum) -> Callable[..., User]:
    allowed = {role for role in roles}
    min_role = max(allowed, key=lambda r: ROLE_SCORE.get(r, -1)) if allowed else None

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not allowed:
            return current_user
        if current_user.role in allowed:
            return current_user
        if min_role and role_at_least(current_user.role, min_role):
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return dependency


def require_scope(scope_key: str, min_level: int) -> Callable[..., User]:
    """按数据库分级权限策略校验权限域等级。"""

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.services.access_control import user_has_scope_level

        if user_has_scope_level(db, user=current_user, scope_key=scope_key, min_level=min_level):
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    return dependency
