from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.db.models.user import RoleEnum, MemberTierEnum


class ProfileResponse(BaseModel):
    id: str
    telephone: Optional[str] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    role: RoleEnum
    membership_tier: MemberTierEnum | None = None
    created_at: Optional[datetime] = None
    lastlogin_at: Optional[datetime] = None


class PhoneUpdateRequest(BaseModel):
    new_telephone: str = Field(..., min_length=11, max_length=11)
    otp: str = Field(...)


class PasswordChangeRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=16)
    old_password: Optional[str] = Field(default=None)
    otp: Optional[str] = Field(default=None)
    telephone: Optional[str] = Field(default=None, min_length=11, max_length=11)

    @field_validator('new_password')
    @classmethod
    def strip_password(cls, v: str) -> str:
        return v.strip()

    @field_validator('old_password', 'otp', 'telephone', mode='before')
    @classmethod
    def optional_strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            return v
        return v

    @field_validator('otp')
    @classmethod
    def require_old_or_otp(cls, v, info):
        data = info.data
        old_password = data.get('old_password')
        otp_val = v
        if (not old_password or not old_password.strip()) and (not otp_val or not otp_val.strip()):
            raise ValueError('必须提供原密码或短信验证码')
        return otp_val


# =========================
# 常用打球人邀请相关
# =========================
class ProfileInviteResponse(BaseModel):
    qrcode_url: str = Field(..., description="完整的微信授权URL，APP生成二维码展示")


class ProfileJoinRequest(BaseModel):
    owner_id: str = Field(..., description="邀请人ID，从URL参数state获取")
    wechat_code: str = Field(..., description="微信授权码")


class ProfileInfo(BaseModel):
    id: str
    name: str
    avatar_url: str | None = None
    is_wechat: bool = False


class ProfileJoinResponse(BaseModel):
    success: bool
    message: str
    profile: ProfileInfo | None = None
