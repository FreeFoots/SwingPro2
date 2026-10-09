from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from app.core.deps import get_db, get_current_user, get_redis
from app.schemas.profile import (
    ProfileResponse,
    PhoneUpdateRequest,
    PasswordChangeRequest,
)
from app.db.models.user import User, RoleEnum
from app.services.otp import verify_otp
from app.services.auth import validate_password_strength
from app.services.activity_helper import log_password_change

router = APIRouter()


def _exposed_membership_tier(user: User) -> str | None:
    if user.role in (RoleEnum.user, RoleEnum.business):
        return user.membership_tier
    return None


@router.get("/me", response_model=ProfileResponse)
async def get_profile(current_user: User = Depends(get_current_user)) -> ProfileResponse:
    return ProfileResponse(
        id=current_user.id,
        telephone=current_user.telephone,
        username=current_user.username,
        avatar_url=current_user.avatar_url,
        role=current_user.role,
        membership_tier=_exposed_membership_tier(current_user),
        created_at=current_user.created_at,
        lastlogin_at=current_user.lastlogin_at,
    )


@router.put("/me/telephone", response_model=ProfileResponse)
async def update_phone(
    payload: PhoneUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    store=Depends(get_redis),
) -> ProfileResponse:
    tel = payload.new_telephone.strip()
    otp = payload.otp.strip()
    ok = await verify_otp(store, tel, otp)
    if not ok:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    existed = (
        db.query(User)
        .filter(User.telephone == tel, User.id != current_user.id)
        .first()
    )
    if existed:
        raise HTTPException(status_code=400, detail="该手机号已被占用")

    current_user.telephone = tel
    db.commit()
    db.refresh(current_user)
    return await get_profile(current_user)


@router.put("/me/password")
async def change_password(
    request: Request,
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    store=Depends(get_redis),
):
    new_password = payload.new_password.strip()
    #print出输入信息
    if not validate_password_strength(new_password):
        raise HTTPException(status_code=400, detail="密码需 8~16 位且包含字母与数字")

    if payload.old_password:
        if not current_user.password or not bcrypt.verify(payload.old_password, current_user.password):
            raise HTTPException(status_code=400, detail="原密码错误")
    else:
        tel = (payload.telephone or current_user.telephone or '').strip()
        if not tel:
            raise HTTPException(status_code=400, detail="未提供手机号用于验证码校验")
        otp = (payload.otp or '').strip()
        ok = await verify_otp(store, tel, otp)
        if not ok:
            raise HTTPException(status_code=400, detail="验证码错误或已过期")

    current_user.password = bcrypt.hash(new_password)
    db.commit()

    # 记录密码修改（敏感操作）
    log_password_change(db, request, current_user, success=True)

    return {"ok": True}
