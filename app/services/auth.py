import re, uuid, hashlib
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select
from passlib.hash import bcrypt
from app.db.models.user import User, RefreshToken
from app.services.invites import validate_invite, mark_invite_used
from app.services.users import ensure_user_active, is_unlimited_role
from app.core.security import create_access_token, gen_refresh_token_pair, now_bj
from app.core.config import settings
from app.services.device_name import resolve_ios_device_name

# =========================
# 密码校验逻辑
# =========================
def validate_password_strength(password: str) -> bool:
    """密码需 8~16 位，且仅允许字母与数字的组合，并同时包含两者"""
    if not (8 <= len(password) <= 16):
        return False
    if not re.fullmatch(r"[A-Za-z0-9]+", password or ""):
        return False
    has_letter = bool(re.search(r"[A-Za-z]", password))
    has_digit = bool(re.search(r"\d", password))
    return has_letter and has_digit

# =========================
# Issue Token + RT 入库
# =========================
SESSION_FIELD_BY_CLIENT = {
    "app": "app_session_id",
    "web": "web_session_id",
}


def _set_session_id(user: User, client_type: str, sid: str) -> None:
    field = SESSION_FIELD_BY_CLIENT.get(client_type)
    if not field:
        raise ValueError("INVALID_CLIENT_TYPE")
    setattr(user, field, sid)


def _clear_session_id(user: User, client_type: str) -> None:
    field = SESSION_FIELD_BY_CLIENT.get(client_type)
    if not field:
        return
    setattr(user, field, None)


def _revoke_active_tokens(db: Session, user_id: str, client_type: str) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.client_type == client_type,
        RefreshToken.revoked == False,
    ).update({RefreshToken.revoked: True}, synchronize_session=False)


def issue_tokens_and_persist_rt(
    db: Session,
    user: User,
    client_type: str,
    rotated_from: int | None = None,
):
    if client_type not in SESSION_FIELD_BY_CLIENT:
        raise ValueError("INVALID_CLIENT_TYPE")

    sid = uuid.uuid4().hex
    at = create_access_token(sub=user.id, role=user.role.value, sid=sid, client_type=client_type)
    _revoke_active_tokens(db, user.id, client_type)
    token_id, secret, rt_plain, rt_hash = gen_refresh_token_pair()
    ttl_days = user.refresh_token_ttl_days or settings.REFRESH_TOKEN_EXPIRE_DAYS
    rt = RefreshToken(
        user_id=user.id,
        secret_hash=rt_hash,
        token_id=token_id,
        client_type=client_type,
        rotated_from=rotated_from,
        expires_at=now_bj() + timedelta(days=ttl_days),
    )
    db.add(rt)
    _set_session_id(user, client_type, sid)
    db.commit()
    db.refresh(rt)
    return at, rt_plain, rt.id

# =========================
# 认证与签发（拆分逻辑，便于前置权限判断）
# =========================
def authenticate_user(
    db: Session,
    telephone: str,
    password: str | None,
    otp_ok: bool | None,
):
    user = db.execute(select(User).where(User.telephone == telephone)).scalar_one_or_none()
    if not ensure_user_active(db, user):
        return None, "USER_NOT_FOUND_OR_DISABLED"

    if password:
        if not user.password or not bcrypt.verify(password, user.password):
            return None, "INVALID_PASSWORD"
    else:
        if not otp_ok:
            return None, "OTP_INVALID_OR_EXPIRED"
    return user, None


def issue_tokens_for_user(
    db: Session,
    user: User,
    client_type: str,
    device_id: str | None = None,
    device_name: str | None = None,
):
    at, rt_plain, _ = issue_tokens_and_persist_rt(db, user, client_type)
    if client_type == "app":
        if device_id:
            user.device_id = device_id
        if device_name:
            user.device_name = resolve_ios_device_name(device_name) or device_name
    user.lastlogin_at = now_bj()
    db.commit()
    return at, rt_plain


def has_active_app_rt(db: Session, user_id: str) -> bool:
    """是否存在未过期且未吊销的 App 端 Refresh Token。"""
    now = now_bj()
    rt = db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.client_type == "app",
            RefreshToken.revoked == False,
            RefreshToken.expires_at >= now,
        )
    ).scalar_one_or_none()
    return rt is not None


def has_device_login_conflict(db: Session, user: User, device_id: str | None) -> bool:
    """
    重复登录校验：
    - 仅当存在未过期 App RT 时生效；
    - 且 device_id 与上次登录设备ID不一致；
    - 且当前时间 < (RT 过期时间 - 6天) 时判定冲突。
    其余情况均允许登录。
    """
    if not device_id:
        return False
    if not user.device_id:
        return False

    now = now_bj()
    rt = (
        db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.client_type == "app",
                RefreshToken.revoked == False,
                RefreshToken.expires_at >= now,
            ).order_by(RefreshToken.expires_at.desc())
        )
        .scalars()
        .first()
    )
    if not rt:
        return False

    if user.device_id == device_id:
        return False

    return now < (rt.expires_at - timedelta(days=6))


def get_wechat_user(db: Session, unionid: str):
    user = db.execute(select(User).where(User.wechat_unionid == unionid)).scalar_one_or_none()
    if not user:
        return None, "WECHAT_NOT_BOUND"
    if not ensure_user_active(db, user):
        return None, "USER_DISABLED"
    return user, None


def sync_wechat_profile(db: Session, user: User, wx_info: dict | None) -> None:
    # 更新昵称与头像（如果有变化）
    if not wx_info:
        return
    nickname = wx_info.get("nickname")
    avatar_url = wx_info.get("avatar_url")
    changed = False
    player_updates = {}
    if nickname and user.username != nickname:
        user.username = nickname
        changed = True
        player_updates["name"] = nickname
    if avatar_url and user.avatar_url != avatar_url:
        user.avatar_url = avatar_url
        changed = True
        player_updates["avatar_url"] = avatar_url

    # 若主账号信息发生变更，同步更新打球人列表中的头像/昵称
    if changed and user.wechat_unionid:
        from app.db.models.user import Player
        if player_updates:
            update_payload = {}
            if "name" in player_updates:
                update_payload[Player.name] = player_updates["name"]
            if "avatar_url" in player_updates:
                update_payload[Player.avatar_url] = player_updates["avatar_url"]
            if update_payload:
                db.query(Player).filter(
                    Player.wechat_unionid == user.wechat_unionid
                ).update(update_payload, synchronize_session=False)

# =========================
# 注册逻辑（手机号 + 密码 + 邀请码 + 验证码）
# =========================
def register_with_password_otp_invite(
    db: Session,
    telephone: str,
    password: str,
    invite_code: str,
    client_type: str,
):
    existed = db.execute(select(User).where(User.telephone == telephone)).scalar_one_or_none()
    if existed:
        return None, "USER_EXISTS"

    if not validate_password_strength(password):
        return None, "INVALID_PASSWORD_FORMAT"

    inv = validate_invite(db, invite_code)
    if not inv:
        return None, "INVITE_INVALID"

    pwd_hash = bcrypt.hash(password)
    duration_days = inv.duration_days or 30
    user = User(telephone=telephone, password=pwd_hash, status=True)
    if not is_unlimited_role(user.role):
        user.disabled_until = now_bj() + timedelta(days=duration_days)
    db.add(user)
    db.commit()
    db.refresh(user)

    mark_invite_used(db, inv, user.id, telephone)

    at, rt_plain, _ = issue_tokens_and_persist_rt(db, user, client_type)
    user.lastlogin_at = now_bj()
    db.commit()
    return {"access_token": at, "refresh_token": rt_plain, "user_id": user.id}, None

# =========================
# 登录逻辑（密码 or 验证码）
# =========================
def login(db: Session, telephone: str, password: str | None, otp_ok: bool | None, client_type: str):
    user, err = authenticate_user(db, telephone, password, otp_ok)
    if err:
        return None, err
    at, rt_plain = issue_tokens_for_user(db, user, client_type)
    return {"access_token": at, "refresh_token": rt_plain, "user": user}, None

# =========================
# 刷新令牌（带旋转）
# =========================
def split_rt(rt_plain: str):
    try:
        token_id, secret = rt_plain.split(".", 1)
        return token_id, secret
    except Exception:
        return None, None

def refresh_rotate(db: Session, rt_plain: str):
    token_id, secret = split_rt(rt_plain)
    if not token_id or not secret:
        return None, "INVALID_RT_FORMAT"

    rt = db.execute(select(RefreshToken).where(RefreshToken.token_id == token_id)).scalar_one_or_none()
    if not rt:
        return None, "RT_NOT_FOUND"
    if rt.revoked:
        return None, "RT_REUSED"
    if rt.expires_at < now_bj():
        return None, "RT_EXPIRED"

    if hashlib.sha256(secret.encode()).hexdigest() != rt.secret_hash:
        return None, "RT_MISMATCH"

    user = db.execute(select(User).where(User.id == rt.user_id)).scalar_one_or_none()
    if not ensure_user_active(db, user):
        return None, "USER_NOT_FOUND_OR_DISABLED"

    client_type = rt.client_type or "app"

    # 旋转
    rt.revoked = True
    at, new_rt_plain, _ = issue_tokens_and_persist_rt(
        db,
        user,
        client_type=client_type,
        rotated_from=rt.id,
    )
    # 将 refresh 视为一次有效登录行为，更新最近登录时间。
    user.lastlogin_at = now_bj()
    db.commit()
    return {
        "access_token": at,
        "refresh_token": new_rt_plain,
        "rt_expires_in_days": user.refresh_token_ttl_days or settings.REFRESH_TOKEN_EXPIRE_DAYS,
        "client_type": client_type,
        "user_id": user.id,
    }, None

# =========================
# 登出（吊销当前 RT）
# =========================
def logout_revoke(db: Session, rt_plain: str):
    token_id, secret = split_rt(rt_plain)
    if not token_id or not secret:
        return False, "INVALID_RT_FORMAT"
    rt = db.execute(select(RefreshToken).where(RefreshToken.token_id == token_id)).scalar_one_or_none()
    if not rt:
        return False, "RT_NOT_FOUND"
    if hashlib.sha256(secret.encode()).hexdigest() != rt.secret_hash:
        return False, "RT_MISMATCH"
    rt.revoked = True
    user = db.get(User, rt.user_id)
    if user:
        user.device_id = None
        user.device_name = None
        _clear_session_id(user, rt.client_type or "app")
    db.commit()
    return True, None

# =========================
# 微信登录与绑定
# =========================
def login_by_wechat(db: Session, unionid: str, wx_info: dict | None = None, client_type: str = "app"):
    user, err = get_wechat_user(db, unionid)
    if err:
        return None, err
    sync_wechat_profile(db, user, wx_info)
    at, rt_plain = issue_tokens_for_user(db, user, client_type)

    return {
        "access_token": at,
        "refresh_token": rt_plain,
        "user": user
    }, None

def bind_wechat_to_user(db: Session, user_id: str, unionid: str, wx_info: dict = None):
    existing = db.execute(select(User).where(User.wechat_unionid == unionid)).scalar_one_or_none()
    if existing:
        if existing.id == user_id:
            # 已绑定时也同步一次微信资料（含 players 表）
            sync_wechat_profile(db, existing, wx_info)
            return True, "ALREADY_BOUND"
        return False, "WECHAT_BOUND_TO_OTHER"

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        return False, "USER_NOT_FOUND"

    user.wechat_unionid = unionid

    if wx_info:
        nickname = wx_info.get("nickname")
        avatar_url = wx_info.get("avatar_url")
        if nickname:
            user.username = nickname
        if avatar_url:
            user.avatar_url = avatar_url
    from app.services.players import add_wechat_profile

    nickname = wx_info.get("nickname") if wx_info else None
    avatar_url = wx_info.get("avatar_url") if wx_info else None

    # 自动将绑定的微信加入到常用打球人，并标记为主账号
    player, err = add_wechat_profile(
        db,
        user_id,
        unionid,
        nickname=nickname,
        avatar_url=avatar_url,
        is_self=True,
        active=True
    )
    if err:
        print(f"Warning: Failed to add wechat profile for user {user_id}: {err}")
    else:
        print(f"Successfully added wechat profile for user {user_id}, player_id={player.id}")

    db.commit()
    return True, None
