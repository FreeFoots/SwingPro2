from pydantic import BaseModel, Field
from datetime import datetime

# send-code
class SendOTPRequest(BaseModel):
    telephone: str = Field(min_length=6)

# register
class RegisterRequest(BaseModel):
    telephone: str
    password: str
    invite_code: str
    otp: str

# login（同一个接口，支持两种方式）
class LoginRequest(BaseModel):
    telephone: str
    password: str | None = None
    otp: str | None = None


class LoginAppRequest(LoginRequest):
    device_id: str
    device_name: str | None = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    rt_expires_in_days: int | None = None
    token_type: str = "Bearer"
    expires_in: int
    current_time: datetime


class LoginAppResponse(BaseModel):
    id: str
    telephone: str
    username: str | None = None
    avatar_url: str | None = None
    remaining_valid_seconds: int | None = None
    role: str
    membership_tier: str | None = None
    unionid: str | None = None
    access_token: str
    refresh_token: str
    rt_expires_in_days: int | None = None
    token_type: str = "Bearer"
    expires_in: int
    current_time: datetime


# refresh/logout
class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

# WeChat（app 端已获取 unionid，直接传入）
class WeChatLoginRequest(BaseModel):
    code: str
    device_id: str
    device_name: str | None = None


class WeChatBindRequest(BaseModel):
    code: str


class WeChatWebLoginRequest(BaseModel):
    code: str
    device_id: str
    device_name: str | None = None


class WeChatWebBindRequest(BaseModel):
    code: str
    user_id: str | None = None  # 可选，若不传则使用当前登录用户


# 扫码登录
class QRLoginCreateResponse(BaseModel):
    qr_token: str
    expires_in: int
    qrcode_url: str | None = None
    qr_image_url: str | None = None  # 直接的二维码图片地址


class QRLoginConfirmRequest(BaseModel):
    qr_token: str


class QRLoginPollResponse(BaseModel):
    status: str  # pending | ready | error
    message: str | None = None
    id: str | None = None
    telephone: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    role: str | None = None
    unionid: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None

# invite
class InviteCreateRequest(BaseModel):
    expired_at: datetime | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)

class InviteResponse(BaseModel):
    code: str
    status: str
    expired_at: datetime | None = None
    duration_days: int | None = None
