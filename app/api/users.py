from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.hash import bcrypt
from datetime import timedelta
from app.core.deps import get_db, require_scope
from app.schemas.user import (
    UserRoleUpdateRequest,
    UserStatusUpdateRequest,
    UserMembershipTierUpdateRequest,
    AdminResetUserDeviceRequest,
    AdminResetUserTelephoneRequest,
    AdminResetUserPasswordRequest,
    AdminSetUserRtTtlRequest,
    UserOut,
    UserListResponse,
)
from app.services.users import (
    change_user_role,
    search_users,
    set_user_status,
    set_user_membership_tier,
)
from app.db.models.user import User, RoleEnum
from app.db.models.user import RefreshToken
from app.db.models.video import Video
from app.services.auth import validate_password_strength
from app.services.activity_helper import log_role_change, log_user_status_change
from app.core.security import now_bj

router = APIRouter()

ROLE_PRIORITY = {
    RoleEnum.user: 0,
    RoleEnum.business: 1,
    RoleEnum.admin: 2,
    RoleEnum.super_admin: 3,
    RoleEnum.system_admin: 4,
}


def _role_level(role: RoleEnum | None) -> int:
    return ROLE_PRIORITY.get(role, -1)


def _get_manageable_target(user_id: str, current_user: User, db: Session) -> User:
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")
    if target.id == current_user.id:
        raise HTTPException(status_code=403, detail="不可对自己执行该操作")
    if _role_level(target.role) >= _role_level(current_user.role):
        raise HTTPException(status_code=403, detail="无权操作级别高于或等于自己的用户")
    return target


@router.get("", response_model=UserListResponse)
def list_users(
    query: str | None = Query(default=None, alias="q"),
    role: RoleEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    scope: str | None = Query(default=None),
    current_user: User = Depends(require_scope("user", 1)),
    db: Session = Depends(get_db),
):
    users = search_users(db, keyword=query, role=role, limit=limit)
    current_level = _role_level(current_user.role)

    user_ids = [u.id for u in users]
    video_count_map: dict[str, int] = {}
    if user_ids:
        rows = (
            db.query(Video.owner_id, func.count(Video.id))
            .filter(Video.deleted == False, Video.owner_id.in_(user_ids))
            .group_by(Video.owner_id)
            .all()
        )
        video_count_map = {str(owner_id): int(count) for owner_id, count in rows if owner_id}

    items = [
        UserOut(
            id=u.id,
            telephone=u.telephone,
            username=u.username,
            avatar_url=u.avatar_url,
            video_count=video_count_map.get(str(u.id), 0),
            device_id=u.device_id,
            device_name=u.device_name,
            role=u.role,
            membership_tier=u.membership_tier if u.role in (RoleEnum.user, RoleEnum.business) else None,
            status=u.status,
            disabled_until=u.disabled_until,
            refresh_token_ttl_days=u.refresh_token_ttl_days,
            can_manage=u.id != current_user.id and _role_level(u.role) < current_level,
        )
        for u in users
    ]

    return UserListResponse(total=len(items), items=items)


@router.patch("/{user_id}/role", response_model=UserOut)
def update_user_role(
    request: Request,
    user_id: str,
    payload: UserRoleUpdateRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    # 权限检查：不可对自己操作，不可操作同级或上级
    if target.id == current_user.id:
        raise HTTPException(status_code=403, detail="不可对自己进行角色变更")

    if _role_level(target.role) >= _role_level(current_user.role):
        raise HTTPException(status_code=403, detail="无权操作级别高于或等于自己的用户")

    if payload.role == RoleEnum.super_admin and current_user.role != RoleEnum.system_admin:
        raise HTTPException(status_code=403, detail="仅系统管理员可指派超级管理员角色")

    # 权限检查：变更后的等级必须低于当前操作者的等级
    if _role_level(payload.role) >= _role_level(current_user.role):
        raise HTTPException(status_code=403, detail="不可指派等级高于或等于自己的角色")

    old_role = target.role.value if target.role else None

    updated, err = change_user_role(
        db,
        actor=current_user,
        target=target,
        new_role=payload.role,
    )

    if err == "FORBIDDEN":
        raise HTTPException(status_code=403, detail="当前用户无权调整角色")
    if err == "SELF_UPDATE_FORBIDDEN":
        raise HTTPException(status_code=403, detail="不可自行提升或降低角色")
    if err == "ROLE_TOO_HIGH":
        raise HTTPException(status_code=403, detail="不可指派高于自身权限的角色")
    if err == "FORBIDDEN_TARGET":
        raise HTTPException(status_code=403, detail="目标用户不允许被调整")
    if err == "PEER_FORBIDDEN":
        raise HTTPException(status_code=403, detail="不可调整与自身同级的账号")
    if err:
        raise HTTPException(status_code=400, detail=err)

    # 记录权限变更（敏感操作）
    log_role_change(
        db, request, current_user, target,
        old_role=old_role,
        new_role=payload.role.value,
        success=True
    )

    return updated


@router.patch("/{user_id}/status", response_model=UserOut)
def update_user_status(
    request: Request,
    user_id: str,
    payload: UserStatusUpdateRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    # 权限检查：不可对自己操作，不可操作同级或上级
    if target.id == current_user.id:
        raise HTTPException(status_code=403, detail="不可对自己进行状态变更")

    if _role_level(target.role) >= _role_level(current_user.role):
        raise HTTPException(status_code=403, detail="无权操作级别高于或等于自己的用户")

    if payload.duration_days is not None and payload.duration_days <= 0:
        raise HTTPException(status_code=400, detail="生效天数必须为正整数")

    updated = set_user_status(
        db,
        target=target,
        enabled=payload.enabled,
        duration_days=payload.duration_days,
    )

    # 记录行为
    log_user_status_change(db, request, current_user, target, enabled=payload.enabled, success=True)

    return updated


@router.patch("/{user_id}/membership-tier", response_model=UserOut)
def update_user_membership_tier(
    user_id: str,
    payload: UserMembershipTierUpdateRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = _get_manageable_target(user_id, current_user, db)

    try:
        updated = set_user_membership_tier(
            db,
            target=target,
            membership_tier=payload.membership_tier,
        )
    except ValueError as exc:
        if str(exc) == "ROLE_NOT_TIERED":
            raise HTTPException(status_code=400, detail="仅普通用户或业务员支持会员等级")
        raise

    return updated


@router.patch("/{user_id}/device/reset")
def reset_user_device(
    user_id: str,
    payload: AdminResetUserDeviceRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = _get_manageable_target(user_id, current_user, db)

    target.device_id = None
    if payload.clear_name:
        target.device_name = None
    target.app_session_id = None

    db.query(RefreshToken).filter(
        RefreshToken.user_id == target.id,
        RefreshToken.client_type == "app",
        RefreshToken.revoked == False,
    ).update({RefreshToken.revoked: True}, synchronize_session=False)

    db.commit()
    return {"ok": True, "message": "设备标识已重置"}


@router.patch("/{user_id}/telephone/reset", response_model=UserOut)
def reset_user_telephone(
    user_id: str,
    payload: AdminResetUserTelephoneRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = _get_manageable_target(user_id, current_user, db)
    tel = payload.new_telephone.strip()
    if not tel:
        raise HTTPException(status_code=400, detail="手机号不能为空")

    existed = db.query(User).filter(User.telephone == tel, User.id != target.id).first()
    if existed:
        raise HTTPException(status_code=400, detail="该手机号已被占用")

    target.telephone = tel
    db.commit()
    db.refresh(target)
    return target


@router.patch("/{user_id}/password/reset")
def reset_user_password(
    user_id: str,
    payload: AdminResetUserPasswordRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = _get_manageable_target(user_id, current_user, db)
    pwd = payload.new_password.strip()
    if not validate_password_strength(pwd):
        raise HTTPException(status_code=400, detail="密码需 8~16 位且包含字母与数字")

    target.password = bcrypt.hash(pwd)
    db.commit()
    return {"ok": True, "message": "密码已重置"}


@router.patch("/{user_id}/rt-ttl")
def set_user_rt_ttl(
    user_id: str,
    payload: AdminSetUserRtTtlRequest,
    current_user: User = Depends(require_scope("user", 2)),
    db: Session = Depends(get_db),
):
    target = _get_manageable_target(user_id, current_user, db)
    ttl_days = int(payload.rt_ttl_days)
    if ttl_days <= 0 or ttl_days > 365:
        raise HTTPException(status_code=400, detail="rt_ttl_days 需在 1~365 之间")

    old_ttl_days = int(target.refresh_token_ttl_days or 0)
    delta_days = ttl_days - old_ttl_days
    target.refresh_token_ttl_days = ttl_days

    # 立即作用到当前有效RT：仅调整剩余时长，不改动原有RT token。
    # 例如 7d -> 15d，则在“当前剩余时长”基础上增加 8d。
    now = now_bj()
    active_tokens = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == target.id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > now,
        )
        .all()
    )

    latest_expire = None
    for rt in active_tokens:
        adjusted_expire = rt.expires_at + timedelta(days=delta_days)
        # 当缩短有效期导致结果早于当前时间时，按立即过期处理。
        if adjusted_expire < now:
            adjusted_expire = now
        rt.expires_at = adjusted_expire
        if latest_expire is None or adjusted_expire > latest_expire:
            latest_expire = adjusted_expire

    db.commit()
    return {
        "ok": True,
        "user_id": target.id,
        "rt_ttl_days": ttl_days,
        "previous_rt_ttl_days": old_ttl_days,
        "delta_days": delta_days,
        "active_rt_count": len(active_tokens),
        "active_rt_expire_at": latest_expire.isoformat() if latest_expire else None,
    }
