from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional


class InviteCreateRequest(BaseModel):
    max_uses: int | None = None  #不做计数，仅做启用/过期
    expired_at: datetime | None = None
    duration_days: int | None = None


class InviteCodeResponse(BaseModel):
    code: str
    status: str
    expired_at: datetime | None = None
    duration_days: int | None = None


class InviteItem(BaseModel):
    code: str
    status: str
    expired_at: datetime | None = None
    duration_days: int | None = None
    telephone: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime | None = None


class InviteListResponse(BaseModel):
    total: int
    items: List[InviteItem]
