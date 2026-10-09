from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.core.security import now_bj
from app.db.models.user import User, RoleEnum, MemberTierEnum

UNLIMITED_ROLES = {RoleEnum.admin, RoleEnum.super_admin, RoleEnum.system_admin}
TIERED_ROLES = {RoleEnum.user, RoleEnum.business}


def is_unlimited_role(role: RoleEnum | None) -> bool:
    return role in UNLIMITED_ROLES


def set_user_status(
    db: Session,
    *,
    target: User,
    enabled: bool,
    duration_days: int | None = None,
):
    """启用/禁用用户；启用可设置/延长生效时间"""
    now = now_bj()
    if is_unlimited_role(target.role):
        target.status = bool(enabled)
        target.disabled_until = None
        db.commit()
        db.refresh(target)
        return target
    if enabled:
        if not target.status:
            target.status = True
            days = duration_days or 30
            target.disabled_until = _extend_disabled_until(target.disabled_until, now, days)
        elif duration_days is not None:
            target.disabled_until = _extend_disabled_until(target.disabled_until, now, duration_days)
    else:
        target.status = False
        target.disabled_until = now
    db.commit()
    db.refresh(target)
    return target


def change_user_role(
    db: Session,
    *,
    actor: User,
    target: User,
    new_role: RoleEnum,
) -> tuple[User | None, str | None]:
    if target.role == new_role:
        return target, None

    actor_role = actor.role
    target_role = target.role

    if actor_role in (RoleEnum.user, RoleEnum.business):
        return None, "FORBIDDEN"

    if actor.id == target.id and actor_role != RoleEnum.super_admin and new_role != actor_role:
        return None, "SELF_UPDATE_FORBIDDEN"

    if actor_role == RoleEnum.admin:
        if new_role == RoleEnum.super_admin:
            return None, "ROLE_TOO_HIGH"
        if target_role == RoleEnum.super_admin:
            return None, "FORBIDDEN_TARGET"
        if target_role == RoleEnum.admin and target.id != actor.id:
            return None, "PEER_FORBIDDEN"

    target.role = new_role
    # 升降级后重新初始化会员等级：
    # - user/business: normal
    # - 管理员及以上: None
    if new_role in TIERED_ROLES:
        target.membership_tier = MemberTierEnum.normal.value
    else:
        target.membership_tier = None

    if is_unlimited_role(new_role):
        target.disabled_until = None
    elif is_unlimited_role(target_role) and not is_unlimited_role(new_role):
        target.status = True
        target.disabled_until = now_bj() + timedelta(days=30)
    db.commit()
    db.refresh(target)
    return target, None


def set_user_membership_tier(
    db: Session,
    *,
    target: User,
    membership_tier: MemberTierEnum,
) -> User:
    """设置用户会员等级，仅 user/business 允许设置。"""
    if target.role not in TIERED_ROLES:
        raise ValueError("ROLE_NOT_TIERED")

    target.membership_tier = membership_tier.value
    db.commit()
    db.refresh(target)
    return target


def ensure_user_active(db: Session, user: User | None) -> bool:
    if not user or not user.status:
        return False
    if is_unlimited_role(user.role):
        return True
    if user.disabled_until and now_bj() >= user.disabled_until:
        user.status = False
        db.commit()
        return False
    return True


def search_users(
    db: Session,
    *,
    keyword: str | None = None,
    role: RoleEnum | None = None,
    limit: int = 50,
) -> list[User]:
    stmt = select(User)
    if keyword:
        term = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                User.telephone.ilike(term),
                User.username.ilike(term),
            )
        )
    if role:
        stmt = stmt.where(User.role == role)
    stmt = stmt.order_by(User.created_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    users = list(db.execute(stmt).scalars())
    expired = [
        u for u in users
        if u.status and u.disabled_until and now_bj() >= u.disabled_until and not is_unlimited_role(u.role)
    ]
    if expired:
        for user in expired:
            user.status = False
        db.commit()
    return users


def _extend_disabled_until(current, now, days: int):
    base = current if current and current > now else now
    return base + timedelta(days=days)
