from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List

from app.db.models.user import RoleEnum, MemberTierEnum


class UserRoleUpdateRequest(BaseModel):
    role: RoleEnum


class UserStatusUpdateRequest(BaseModel):
    enabled: bool
    duration_days: int | None = None


class UserMembershipTierUpdateRequest(BaseModel):
    membership_tier: MemberTierEnum


class UserOut(BaseModel):
    id: str
    telephone: Optional[str] = None
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    video_count: int | None = None
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    role: RoleEnum
    membership_tier: MemberTierEnum | None = None
    status: bool | None = None
    disabled_until: datetime | None = None
    refresh_token_ttl_days: int | None = None
    can_manage: bool | None = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total: int
    items: List[UserOut]


class AdminResetUserDeviceRequest(BaseModel):
    clear_name: bool = True


class AdminResetUserTelephoneRequest(BaseModel):
    new_telephone: str


class AdminResetUserPasswordRequest(BaseModel):
    new_password: str


class AdminSetUserRtTtlRequest(BaseModel):
    rt_ttl_days: int
