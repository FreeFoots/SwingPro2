from pydantic import BaseModel, Field

from app.db.models.user import RoleEnum, MemberTierEnum


class RoleScopePolicyUpsertRequest(BaseModel):
    role: RoleEnum
    scope_key: str = Field(..., min_length=2, max_length=64)
    max_level: int = Field(default=0, ge=0, le=9)
    membership_tier: MemberTierEnum | None = None
    description: str | None = None


class RoleScopePolicyItem(BaseModel):
    id: int
    role: RoleEnum
    membership_tier: MemberTierEnum | None = None
    scope_key: str
    max_level: int
    description: str | None = None

    class Config:
        from_attributes = True
