"""
常用打球人相关 Schema
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class PlayerInviteResponse(BaseModel):
    """生成常用打球人邀请二维码响应"""
    qrcode_url: str = Field(..., description="完整的微信授权URL，APP生成二维码展示")


class PlayerJoinRequest(BaseModel):
    """微信扫码加入常用打球人请求"""
    user_id: str = Field(..., description="邀请人ID，从URL参数state获取")
    wechat_code: str = Field(..., description="微信授权码")


class PlayerOut(BaseModel):
    """常用打球人输出"""
    id: int
    wechat_unionid: str
    name: str
    avatar_url: Optional[str] = None
    active: bool = False
    is_self: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class PlayerJoinResponse(BaseModel):
    """微信扫码加入常用打球人响应"""
    success: bool
    message: str
    player: Optional[PlayerOut] = None
    players: Optional[List[PlayerOut]] = None


class PlayerListResponse(BaseModel):
    """常用打球人列表响应"""
    total: int
    items: List[PlayerOut]
    active_wechat_unionid: str | None = None
