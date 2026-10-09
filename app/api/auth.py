from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db, get_redis, get_current_user, role_at_least
from app.core.logging_config import get_logger
from app.schemas.auth import (
    SendOTPRequest, RegisterRequest, LoginRequest,
    TokenResponse, RefreshRequest, LogoutRequest, LoginAppResponse, LoginAppRequest,
    WeChatLoginRequest, WeChatBindRequest,
    WeChatWebLoginRequest, WeChatWebBindRequest,
    QRLoginCreateResponse, QRLoginConfirmRequest, QRLoginPollResponse
)
from app.services.otp import gen_otp, can_send_otp, save_otp, verify_otp, check_otp, consume_otp, send_sms
from app.services.auth import (
    register_with_password_otp_invite,
    authenticate_user, issue_tokens_for_user,
    refresh_rotate, logout_revoke,
    get_wechat_user, sync_wechat_profile,
    bind_wechat_to_user, issue_tokens_and_persist_rt,
    has_device_login_conflict,
)
from app.services.players import add_wechat_profile
from app.core.security import now_bj
from app.db.models.user import RoleEnum, User
from app.services.activity_helper import (
    log_send_otp, log_register, log_login, log_bind_wechat
)
from app.services.wechat import (
    get_wechat_user_info, get_wechat_web_user_info, get_wechat_user_info_app,
    get_wechat_user_detail,
    web_qr_key, build_web_qr_url, extract_qr_image, WEB_QR_TTL, WEB_QR_READY_TTL
)
import uuid, json, hashlib

logger = get_logger(__name__)
def _extract_wechat_id(wx_info: dict | None) -> str:
    """从微信返回中取 unionid（必须存在）。"""
    if not wx_info:
        raise HTTPException(status_code=400, detail="无法获取微信用户信息")
    wechat_id = wx_info.get("unionid")
    if not wechat_id:
        raise HTTPException(status_code=400, detail="微信未返回 unionid")
    return wechat_id

#不进行统一
def _normalize_role(role: RoleEnum | None) -> str:
    if not role:
        return "user"
    if role == RoleEnum.admin:
        return "admin"
    if role == RoleEnum.super_admin:
        return "super_admin"
    if role == RoleEnum.system_admin:
        return "system_admin"
    if role == RoleEnum.business:
        return "business"
    return "user"


def _exposed_membership_tier(user: User) -> str | None:
    if user.role in (RoleEnum.user, RoleEnum.business):
        return user.membership_tier
    return None


def _resolve_client_type(request: Request, fallback: str) -> str:
    header = request.headers.get("x-client-type", "").strip().lower()
    if header in ("app", "web"):
        return header
    return fallback


def _ensure_web_access(user: User, client_type: str) -> None:
    if client_type != "web":
        return
    if not role_at_least(user.role, RoleEnum.admin):
        raise HTTPException(status_code=403, detail="当前账号无权访问 Web 平台")

router = APIRouter()


def _remaining_valid_seconds(user: User) -> int | None:
    if not user or not user.disabled_until:
        return None
    remaining = int((user.disabled_until - now_bj()).total_seconds())
    return max(remaining, 0)


def _rt_expires_in_days(user: User) -> int:
    return int(user.refresh_token_ttl_days or settings.REFRESH_TOKEN_EXPIRE_DAYS)

# =========================
# 1️⃣ 发送验证码
# =========================
@router.post("/send-code")
async def send_code(request: Request, payload: SendOTPRequest, db: Session = Depends(get_db), r=Depends(get_redis)):
    """
    向手机号发送短信验证码。
    """
    # 手机号不存在
    if not await can_send_otp(r, payload.telephone):
        log_send_otp(db, request, payload.telephone, success=False, error="频率限制")
        raise HTTPException(status_code=429, detail="验证码发送过于频繁或超出当日次数限制")

    otp = gen_otp()

    # 发送真实短信
    sms_sent = await send_sms(payload.telephone, otp)
    if not sms_sent:
        log_send_otp(db, request, payload.telephone, success=False, error="短信发送失败")
        raise HTTPException(status_code=500, detail="短信发送失败，请稍后重试")

    await save_otp(r, payload.telephone, otp)

    # 记录行为
    log_send_otp(db, request, payload.telephone, success=True)

    return {
        "ok": True,
        "msg": "验证码已发送",
        "timestamp": now_bj().isoformat()
    }

# =========================
# 2️⃣ 注册（手机号 + 密码 + 邀请码 + 验证码）
# =========================
@router.post("/register", response_model=TokenResponse)
async def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db), r=Depends(get_redis)):
    """
    用户注册流程：
    1. 校验短信验证码；
    2. 校验密码强度（8~16位字母+数字）；
    3. 校验邀请码；
    4. 创建账户并签发 AT/RT。
    """
    # 1. 先校验验证码（仅校验，不消费）
    ok = await check_otp(r, payload.telephone, payload.otp)
    if not ok:
        raise HTTPException(status_code=400, detail="验证码无效")

    # 2. 执行注册
    client_type = _resolve_client_type(request, "web")
    data, err = register_with_password_otp_invite(
        db, telephone=payload.telephone,
        password=payload.password,
        invite_code=payload.invite_code,
        client_type=client_type,
    )

    if err == "USER_EXISTS":
        raise HTTPException(status_code=400, detail="该手机号已注册，请直接登录")
    if err == "INVALID_PASSWORD_FORMAT":
        raise HTTPException(status_code=400, detail="密码需 8~16 位且包含字母与数字")
    if err == "INVITE_INVALID":
        raise HTTPException(status_code=400, detail="邀请码无效")

    # 注册成功后再消费验证码
    await consume_otp(r, payload.telephone, payload.otp)

    # 记录注册行为
    user = data.get("user")
    log_register(db, request, user, success=True)

    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# =========================
# 3️⃣ 登录（支持两种方式：密码 / 验证码）
# =========================
async def _handle_login(
    request: Request,
    payload: LoginRequest,
    db: Session,
    r,
    client_type: str,
    device_id: str | None = None,
    device_name: str | None = None,
):
    otp_ok = None
    if payload.otp is not None:
        otp_ok = await verify_otp(r, payload.telephone, payload.otp)

    user, err = authenticate_user(
        db,
        telephone=payload.telephone,
        password=payload.password,
        otp_ok=otp_ok,
    )

    if err == "USER_NOT_FOUND_OR_DISABLED":
        raise HTTPException(status_code=404, detail="用户不存在或已被禁用")
    if err == "INVALID_PASSWORD":
        raise HTTPException(status_code=400, detail="密码错误")
    if err == "OTP_INVALID_OR_EXPIRED":
        raise HTTPException(status_code=400, detail="验证码无效")

    # 系统管理员禁止登录 App
    if request.url.path.endswith("/login_app"):
        if user and user.role == RoleEnum.system_admin:
            raise HTTPException(status_code=403, detail="系统管理员仅允许在 Web 端登录")

    # App 端设备重复登录校验：
    # 若存在未过期 RT 且设备与上次登录设备不一致，则拦截登录（需先退出登录撤销 RT）
    if client_type == "app" and has_device_login_conflict(db, user, device_id):
        raise HTTPException(status_code=403, detail="检测到重复登录，请先在原设备退出登录")

    # 记录登录行为
    _ensure_web_access(user, client_type)
    at, rt_plain = issue_tokens_for_user(
        db,
        user,
        client_type,
        device_id=device_id,
        device_name=device_name,
    )
    data = {"access_token": at, "refresh_token": rt_plain, "user": user}
    method = "otp" if payload.otp else "password"
    log_login(db, request, user, method=method, client_type=client_type, success=True)

    return data


@router.post("/login", response_model=TokenResponse)
async def login_entry(request: Request, payload: LoginRequest, db: Session = Depends(get_db), r=Depends(get_redis)):
    """
    登录方式：
    - 密码登录：telephone + password
    - 验证码登录：telephone + otp
    """
    client_type = _resolve_client_type(request, "web")
    data = await _handle_login(request, payload, db, r, client_type)
    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/login_app", response_model=LoginAppResponse)
async def login_app(request: Request, payload: LoginAppRequest, db: Session = Depends(get_db), r=Depends(get_redis)):
    """
    登录方式：
    - 密码登录：telephone + password
    - 验证码登录：telephone + otp
    """
    data = await _handle_login(
        request,
        payload,
        db,
        r,
        "app",
        device_id=payload.device_id,
        device_name=payload.device_name,
    )
    user = data["user"]

    # 超级管理员也允许登录App
    # if user.role == RoleEnum.super_admin:
    #     raise HTTPException(status_code=403, detail="该用户不可访问")

    return LoginAppResponse(
        id=user.id,
        telephone=user.telephone,
        username=user.username,
        avatar_url=user.avatar_url,
        remaining_valid_seconds=_remaining_valid_seconds(user),
        role=_normalize_role(user.role),
        membership_tier=_exposed_membership_tier(user),
        unionid=user.wechat_unionid,
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        rt_expires_in_days=_rt_expires_in_days(user),
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# =========================
# 4️⃣ 令牌刷新（旋转）
# =========================
@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, payload: RefreshRequest, db: Session = Depends(get_db), r=Depends(get_redis)):
    """
    刷新 Access Token：
    - 校验 RT（格式、哈希、是否撤销、是否过期）；
    - 吊销旧 RT；
    - 签发新 AT & RT。
    - 并发保护：如果检测到 RT 被重复使用，但距被撤销时间很短（<20s），允许返回同一对新令牌
    """
    if r and payload.refresh_token:
        # 并发刷新保护：检查缓存
        rt_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
        cache_key = f"refresh_grace:{rt_hash}"
        cached_result = await r.get(cache_key)
        if cached_result:
            try:
                data = json.loads(cached_result)
                user_id = data.get("user_id")
                if user_id:
                    user = db.get(User, user_id)
                    if user:
                        log_login(
                            db,
                            request,
                            user,
                            method="refresh",
                            client_type=data.get("client_type") or "app",
                            success=True,
                        )
                return TokenResponse(
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    rt_expires_in_days=data.get("rt_expires_in_days"),
                    current_time=now_bj(),
                    expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
                )
            except Exception:
                pass

    data, err = refresh_rotate(db, payload.refresh_token)
    if err == "RT_EXPIRED":
        raise HTTPException(status_code=401, detail="刷新令牌已过期，请重新登录")
    if err == "RT_REVOKED":
        raise HTTPException(status_code=401, detail="刷新令牌已失效，请重新登录")
    if err == "RT_MISMATCH":
        raise HTTPException(status_code=401, detail="刷新令牌验证失败")
    if err == "RT_REUSED":
        # 此处可以做进一步的日志报警
        raise HTTPException(status_code=401, detail="检测到刷新令牌重复使用，请重新登录")
    if err:
        raise HTTPException(status_code=400, detail=err or "令牌刷新失败")

    user_id = data.get("user_id")
    if user_id:
        user = db.get(User, user_id)
        if user:
            log_login(
                db,
                request,
                user,
                method="refresh",
                client_type=data.get("client_type") or "app",
                success=True,
            )

    # 并发刷新保护：写入缓存 (有效期 20s)
    if r and payload.refresh_token:
        rt_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
        cache_key = f"refresh_grace:{rt_hash}"
        await r.setex(cache_key, 20, json.dumps(data))

    return TokenResponse(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        rt_expires_in_days=data.get("rt_expires_in_days"),
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

# =========================
# 5️⃣ 登出（吊销当前 RT）
# =========================
@router.post("/logout")
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    """
    登出当前设备：
    - 校验 Refresh Token；
    - 将对应记录 revoked = True。
    """
    ok, err = logout_revoke(db, payload.refresh_token)
    if not ok:
        if err == "RT_REVOKED":
            raise HTTPException(status_code=401, detail="刷新令牌已失效")
        if err == "RT_EXPIRED":
            raise HTTPException(status_code=401, detail="刷新令牌已过期")
        if err == "RT_REUSED":
            raise HTTPException(status_code=401, detail="检测到刷新令牌重复使用")
        if err == "RT_MISMATCH":
            raise HTTPException(status_code=401, detail="刷新令牌验证失败")
        if err:
            raise HTTPException(status_code=400, detail=err or "登出失败")

    return {
        "ok": True,
        "message": "已登出"
    }

# =========================
# 6️⃣ 微信登录与绑定（移动应用；网站扫码单独在 wechat-qr 模块）
# =========================
def _wechat_login_by_wechat_id(
    request: Request,
    db: Session,
    unionid: str,
    wx_info: dict | None = None,
    client_type: str = "app",
    device_id: str | None = None,
    device_name: str | None = None,
) -> LoginAppResponse:
    user, err = get_wechat_user(db, unionid)
    if err:
        if err == "WECHAT_NOT_BOUND":
            raise HTTPException(status_code=403, detail="该微信未绑定账号，请先登录并绑定")
        if err == "USER_DISABLED":
            raise HTTPException(status_code=403, detail="账号已被禁用")
        raise HTTPException(status_code=400, detail="微信登录失败")

    if client_type == "app" and user.role == RoleEnum.system_admin:
        raise HTTPException(status_code=403, detail="系统管理员仅允许在 Web 端登录")

    if client_type == "app" and has_device_login_conflict(db, user, device_id):
        raise HTTPException(status_code=403, detail="检测到重复登录，请先在原设备退出登录")

    _ensure_web_access(user, client_type)
    sync_wechat_profile(db, user, wx_info)
    at, rt_plain = issue_tokens_for_user(
        db,
        user,
        client_type,
        device_id=device_id,
        device_name=device_name,
    )
    log_login(db, request, user, method="wechat", client_type=client_type, success=True)
    return LoginAppResponse(
        id=user.id,
        telephone=user.telephone,
        username=user.username,
        avatar_url=user.avatar_url,
        remaining_valid_seconds=_remaining_valid_seconds(user),
        role=_normalize_role(user.role),
        membership_tier=_exposed_membership_tier(user),
        unionid=user.wechat_unionid,
        access_token=at,
        refresh_token=rt_plain,
        rt_expires_in_days=_rt_expires_in_days(user),
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


def _wechat_bind_by_wechat_id(
    request: Request,
    db: Session,
    current_user: User,
    unionid: str,
    wx_info: dict = None,
    client_type: str = "app",
) -> LoginAppResponse:
    _ensure_web_access(current_user, client_type)
    ok, err = bind_wechat_to_user(
        db,
        current_user.id,
        unionid,
        wx_info,
    )
    if not ok:
        if err == "ALREADY_BOUND":
            # 即使已绑定，也返回用户信息（视为成功）
            pass
        elif err == "WECHAT_BOUND_TO_OTHER":
            raise HTTPException(status_code=400, detail="该微信已被其他账号绑定")
        else:
            raise HTTPException(status_code=400, detail="绑定失败")

    log_bind_wechat(db, request, current_user, unionid, success=True)

    # 签发新令牌（或使用现有会话，这里选择签发新令牌以保持一致性）
    at, rt_plain, _ = issue_tokens_and_persist_rt(db, current_user, client_type)
    # 输出返回内容
    return LoginAppResponse(
        id=current_user.id,
        telephone=current_user.telephone,
        username=current_user.username,
        avatar_url=current_user.avatar_url,
        remaining_valid_seconds=_remaining_valid_seconds(current_user),
        role=_normalize_role(current_user.role),
        membership_tier=_exposed_membership_tier(current_user),
        unionid=current_user.wechat_unionid,
        access_token=at,
        refresh_token=rt_plain,
        rt_expires_in_days=_rt_expires_in_days(current_user),
        current_time=now_bj(),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/wechat-login", response_model=LoginAppResponse)
async def wechat_login(request: Request, payload: WeChatLoginRequest, db: Session = Depends(get_db)):
    """
    微信本机登录（app）
    """
    wx_info = await get_wechat_user_info_app(payload.code)
    wechat_id = _extract_wechat_id(wx_info)
    return _wechat_login_by_wechat_id(
        request,
        db,
        wechat_id,
        wx_info,
        client_type="app",
        device_id=payload.device_id,
        device_name=payload.device_name,
    )


@router.post("/wechat-bind", response_model=LoginAppResponse)
async def wechat_bind(
    request: Request,
    payload: WeChatBindRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    微信绑定接口 (需登录，移动应用)
    固定使用 WECHAT_APP_ID/SECRET，返回 unionid 作为唯一标识
    """
    # 使用 get_wechat_user_detail 获取完整用户信息（包含昵称、头像）
    wx_info = await get_wechat_user_detail(payload.code)
    wechat_id = _extract_wechat_id(wx_info)
    return _wechat_bind_by_wechat_id(request, db, current_user, wechat_id, wx_info, client_type="app")


@router.post("/wechat-web/login", response_model=LoginAppResponse)
async def wechat_web_login(request: Request, payload: WeChatWebLoginRequest, db: Session = Depends(get_db)):
    """
    微信网站应用登录（扫码后前端获取 code 调用）（web端）
    """
    wx_info = await get_wechat_web_user_info(payload.code)
    wechat_id = _extract_wechat_id(wx_info)
    return _wechat_login_by_wechat_id(
        request,
        db,
        wechat_id,
        wx_info,
        client_type="web",
        device_id=payload.device_id,
        device_name=payload.device_name,
    )


@router.post("/wechat-web/login_app", response_model=LoginAppResponse)
async def wechat_web_login_app(request: Request, payload: WeChatWebLoginRequest, db: Session = Depends(get_db)):
    """
    App 端使用微信网站应用登录
    """
    wx_info = await get_wechat_web_user_info(payload.code)
    wechat_id = _extract_wechat_id(wx_info)
    return _wechat_login_by_wechat_id(
        request,
        db,
        wechat_id,
        wx_info,
        client_type="app",
        device_id=payload.device_id,
        device_name=payload.device_name,
    )


@router.post("/wechat-web/bind_app", response_model=LoginAppResponse)
async def wechat_web_bind_app(
    request: Request,
    payload: WeChatWebBindRequest,
    db: Session = Depends(get_db)
):
    """
    App 端使用微信网站应用绑定
    无需登录，需传入 user_id
    """
    if not payload.user_id:
        raise HTTPException(status_code=400, detail="缺少 user_id")

    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    wx_info = await get_wechat_web_user_info(payload.code)
    wechat_id = _extract_wechat_id(wx_info)

    return _wechat_bind_by_wechat_id(request, db, user, wechat_id, wx_info, client_type="app")


# =========================
# 7️⃣ 扫码登录（跨设备）
# =========================
# QR_LOGIN_TTL = 300  # 二维码有效期（秒）
# QR_LOGIN_READY_TTL = 60  # 确认后结果存活时间


# def _qr_key(token: str) -> str:
#     return f"qr_login:{token}"


# @router.post("/qr/create", response_model=QRLoginCreateResponse)
# async def create_qr_login(r=Depends(get_redis)):
#     """
#     生成扫码登录用的二维码 token（用于待登录设备展示）
#     """
#     token = uuid.uuid4().hex
#     await r.set(_qr_key(token), json.dumps({"status": "pending"}), ex=QR_LOGIN_TTL)
#     return QRLoginCreateResponse(qr_token=token, expires_in=QR_LOGIN_TTL)


# @router.post("/qr/confirm")
# async def confirm_qr_login(
#     payload: QRLoginConfirmRequest,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
#     r=Depends(get_redis),
# ):
#     """
#     扫码设备（已登录）确认登录请求，签发 AT/RT 给待登录设备
#     """
#     key = _qr_key(payload.qr_token)
#     val = await r.get(key)
#     if not val:
#         raise HTTPException(status_code=404, detail="二维码不存在或已过期")
#     try:
#         data = json.loads(val)
#     except Exception:
#         data = {}
#     if data.get("status") == "ready":
#         raise HTTPException(status_code=410, detail="二维码已确认")

#     _ensure_web_access(current_user, "web")

#     at, rt_plain, _ = issue_tokens_and_persist_rt(db, current_user, "web")
#     user_info = {
#         "id": current_user.id,
#         "telephone": current_user.telephone,
#         "username": current_user.username,
#         "avatar_url": current_user.avatar_url,
#         "role": _normalize_role(current_user.role),
#         "unionid": current_user.wechat_unionid,
#     }
#     result = {
#         "status": "ready",
#         "access_token": at,
#         "refresh_token": rt_plain,
#         "token_type": "Bearer",
#         "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
#         "user": user_info,
#     }
#     await r.set(key, json.dumps(result), ex=QR_LOGIN_READY_TTL)
#     return {"ok": True, "message": "已确认，请在扫码端完成登录"}


# @router.get("/qr/poll", response_model=QRLoginPollResponse)
# async def poll_qr_login(qr_token: str, r=Depends(get_redis)):
#     """
#     待登录设备轮询二维码状态：
#     - pending: 未确认
#     - ready: 返回 AT/RT 和用户信息
#     """
#     key = _qr_key(qr_token)
#     val = await r.get(key)
#     if not val:
#         raise HTTPException(status_code=404, detail="二维码不存在或已过期")
#     try:
#         data = json.loads(val)
#     except Exception:
#         data = {}
#     status = data.get("status")
#     if status == "pending":
#         return QRLoginPollResponse(status="pending")
#     if status == "ready":
#         # 不立即删除，依靠 TTL 过期，防止前端网络波动没收到响应
#         # await r.delete(key)
#         user_data = data.get("user", {})
#         return QRLoginPollResponse(
#             status="ready",
#             access_token=data.get("access_token"),
#             refresh_token=data.get("refresh_token"),
#             token_type=data.get("token_type") or "Bearer",
#             expires_in=data.get("expires_in"),
#             id=user_data.get("id"),
#             telephone=user_data.get("telephone"),
#             username=user_data.get("username"),
#             avatar_url=user_data.get("avatar_url"),
#             role=user_data.get("role"),
#             unionid=user_data.get("unionid"),
#         )
#     raise HTTPException(status_code=400, detail="二维码状态异常")


# =========================
# 8️⃣ 微信网站应用扫码（登录/绑定）
# =========================

@router.post("/wechat-qr/login", response_model=QRLoginCreateResponse)
async def wechat_web_login_create(r=Depends(get_redis)):
    """生成网站扫码登录二维码"""
    if not settings.WECHAT_WEB_ID or not settings.WECHAT_WEB_SECRET:
        raise HTTPException(status_code=500, detail="未配置微信网站应用参数")
    token = uuid.uuid4().hex
    await r.set(web_qr_key("login", token), json.dumps({"status": "pending"}), ex=WEB_QR_TTL)
    url = build_web_qr_url("login", token)

    # 尝试提取直接的图片地址
    qr_image_url = await extract_qr_image(url)

    return QRLoginCreateResponse(
        qr_token=token,
        expires_in=WEB_QR_TTL,
        qrcode_url=url,
        qr_image_url=qr_image_url
    )


@router.post("/wechat-qr/login_app", response_model=QRLoginCreateResponse)
async def wechat_web_login_app_create(r=Depends(get_redis)):
    """App 使用的网站扫码登录二维码，先/wechat-qr/login_app后/wechat-web/login_app"""
    if not settings.WECHAT_WEB_ID or not settings.WECHAT_WEB_SECRET:
        raise HTTPException(status_code=500, detail="未配置微信网站应用参数")
    token = uuid.uuid4().hex
    await r.set(web_qr_key("login_app", token), json.dumps({"status": "pending"}), ex=WEB_QR_TTL)
    url = build_web_qr_url("login_app", token)

    qr_image_url = await extract_qr_image(url)

    return QRLoginCreateResponse(
        qr_token=token,
        expires_in=WEB_QR_TTL,
        qrcode_url=url,
        qr_image_url=qr_image_url
    )


@router.post("/wechat-qr/bind_app", response_model=QRLoginCreateResponse)
async def wechat_web_bind_app_create(
    current_user: User = Depends(get_current_user),
    r=Depends(get_redis),
):
    """App 使用的网站扫码绑定二维码（需登录）"""
    if not settings.WECHAT_WEB_ID or not settings.WECHAT_WEB_SECRET:
        raise HTTPException(status_code=500, detail="未配置微信网站应用参数")
    token = uuid.uuid4().hex
    await r.set(
        web_qr_key("bind_app", token),
        json.dumps({"status": "pending", "user_id": current_user.id}),
        ex=WEB_QR_TTL,
    )
    url = build_web_qr_url("bind_app", token)

    qr_image_url = await extract_qr_image(url)

    return QRLoginCreateResponse(
        qr_token=token,
        expires_in=WEB_QR_TTL,
        qrcode_url=url,
        qr_image_url=qr_image_url
    )


@router.get("/wechat_web/callback", response_class=HTMLResponse)
async def wechat_web_callback(request: Request, code: str | None = None, state: str | None = None, r=Depends(get_redis), db: Session = Depends(get_db)):
    """
    微信网站应用扫码回调：state=mode:token
    - login: 若 unionid 已绑定用户，则写入 ready + tokens；未绑定写入错误提示
    - bind: 若 unionid 未绑定，则为 user_id 绑定
    """

    def render_msg(msg: str, token_payload: dict | None = None):
        # 优先使用配置的前端入口
        if settings.WEB_PLATFORM_URL:
            platform_url = settings.WEB_PLATFORM_URL
        else:
            platform_url = f"{request.url.scheme}://{request.url.netloc}/platform.html"

        auth_script = ""
        if token_payload:
            # 安全地序列化 payload 两次：一次构建 JSON 对象，一次编码为 URL 参数
            try:
                # 1. 构造干净的 payload 字典
                clean_payload = {
                  "userId": token_payload["user"]["id"],
                  "role": token_payload["user"]["role"],
                  "telephone": token_payload["user"]["telephone"],
                  "expiresAt": int(now_bj().timestamp() * 1000) + (token_payload.get("expires_in") or 0) * 1000,
                  "accessToken": token_payload["access_token"],
                  "refreshToken": token_payload["refresh_token"]
                }

                # 如果 refresh_token 是对象，尝试提取
                if isinstance(clean_payload["refreshToken"], dict):
                     clean_payload["refreshToken"] = clean_payload["refreshToken"].get("token", "")

                import base64
                import urllib.parse

                # 2. Base64 编码，附加到 URL Fragment 或 Query
                # 为了安全且避免 localStorage 跨端口读写问题，我们直接将 token 传给目标页面
                # 并在目标页面通过 JS 解析
                json_str = json.dumps(clean_payload)
                b64_str = base64.urlsafe_b64encode(json_str.encode()).decode()

                #platform_url 已经可能包含 query 参数?，所以要安全拼接
                join_char = "&" if "?" in platform_url else "?"
                target_url_with_token = f"{platform_url}{join_char}login_token={b64_str}"

                auth_script = f"""
                <script>
                    window.location.replace('{target_url_with_token}');
                </script>
                """
            except Exception as e:
                logger.error(f"Render msg error: {e}")
                auth_script = f"<p>登录跳转失败: {str(e)}</p>"

        return f"""
        <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
                <title>跳转中...</title>
                <style>
                    body {{ display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; font-family: -apple-system, sans-serif; background-color: #f5f5f5; }}
                    .card {{ background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; color: #333; }}
                </style>
            </head>
            <body>
                <div class="card">{msg}</div>
                {auth_script}
            </body>
        </html>
        """

    if not code or not state:
        return HTMLResponse(render_msg("缺少 code 或 state"))

    # 根据配置剥离 state 前缀（如 test_）
    if settings.WECHAT_STATE_PREFIX and state.startswith(settings.WECHAT_STATE_PREFIX):
        state = state[len(settings.WECHAT_STATE_PREFIX):]

    try:
        mode, token = state.split(":", 1)
    except ValueError:
        return HTMLResponse(render_msg("state 无效"))
    key = web_qr_key(mode, token)
    val = await r.get(key)
    if not val:
        return HTMLResponse(render_msg("二维码不存在或已过期"))
    try:
        data = json.loads(val)
    except Exception:
        data = {}

    wx_info = await get_wechat_web_user_info(code)
    wechat_id = _extract_wechat_id(wx_info)
    if not wechat_id:
        await r.set(key, json.dumps({"status": "error", "message": "无法获取微信用户信息"}), ex=WEB_QR_READY_TTL)
        return HTMLResponse(render_msg("无法获取微信用户信息"))

    if mode == "login":
        try:
            # 若工作组成员，抛 403
            resp = _wechat_login_by_wechat_id(request, db, wechat_id, wx_info, client_type="web")
            result = {
                "status": "ready",
                "access_token": resp.access_token,
                "refresh_token": resp.refresh_token,
                "token_type": "Bearer",
                "expires_in": resp.expires_in,
                "user": {
                    "id": resp.id,
                    "telephone": resp.telephone,
                    "username": resp.username,
                    "avatar_url": resp.avatar_url,
                    "role": resp.role,
                    "unionid": resp.unionid,
                },
            }
            await r.set(key, json.dumps(result), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("登录成功，正在进入平台…", result))
        except HTTPException as exc:
            await r.set(key, json.dumps({"status": "error", "message": exc.detail}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg(str(exc.detail)))

    elif mode == "bind":
        user_id = data.get("user_id")
        if not user_id:
            await r.set(key, json.dumps({"status": "error", "message": "缺少用户信息"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("缺少用户信息"))
        user = db.get(User, user_id)
        if not user:
            await r.set(key, json.dumps({"status": "error", "message": "用户不存在"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("用户不存在"))
        if not user.status:
            await r.set(key, json.dumps({"status": "error", "message": "用户已禁用"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("用户已禁用"))

        try:
            resp = _wechat_bind_by_wechat_id(request, db, user, wechat_id, wx_info, client_type="web")
            result = {
                "status": "ready",
                "access_token": resp.access_token,
                "refresh_token": resp.refresh_token,
                "token_type": "Bearer",
                "expires_in": resp.expires_in,
                "user": {
                    "id": resp.id,
                    "telephone": resp.telephone,
                    "username": resp.username,
                    "avatar_url": resp.avatar_url,
                    "role": resp.role,
                    "unionid": resp.unionid,
                },
            }
            await r.set(key, json.dumps(result), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("绑定成功"))
        except HTTPException as exc:
            await r.set(key, json.dumps({"status": "error", "message": exc.detail}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg(str(exc.detail)))

    elif mode == "login_app":
        try:
            resp = _wechat_login_by_wechat_id(request, db, wechat_id, wx_info, client_type="app")
            result = {
                "status": "ready",
                "access_token": resp.access_token,
                "refresh_token": resp.refresh_token,
                "token_type": "Bearer",
                "expires_in": resp.expires_in,
                "user": {
                    "id": resp.id,
                    "telephone": resp.telephone,
                    "username": resp.username,
                    "avatar_url": resp.avatar_url,
                    "role": resp.role,
                    "unionid": resp.unionid,
                },
            }
            await r.set(key, json.dumps(result), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("APP登录成功", result))
        except HTTPException as exc:
            await r.set(key, json.dumps({"status": "error", "message": exc.detail}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg(str(exc.detail)))

    elif mode == "bind_app":
        user_id = data.get("user_id")
        if not user_id:
            await r.set(key, json.dumps({"status": "error", "message": "缺少用户信息"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("缺少用户信息"))
        user = db.get(User, user_id)
        if not user:
            await r.set(key, json.dumps({"status": "error", "message": "用户不存在"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("用户不存在"))
        if not user.status:
            await r.set(key, json.dumps({"status": "error", "message": "用户已禁用"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("用户已禁用"))

        try:
            resp = _wechat_bind_by_wechat_id(request, db, user, wechat_id, wx_info, client_type="app")
            result = {
                "status": "ready",
                "access_token": resp.access_token,
                "refresh_token": resp.refresh_token,
                "token_type": "Bearer",
                "expires_in": resp.expires_in,
                "user": {
                    "id": resp.id,
                    "telephone": resp.telephone,
                    "username": resp.username,
                    "avatar_url": resp.avatar_url,
                    "role": resp.role,
                    "unionid": resp.unionid,
                },
            }
            await r.set(key, json.dumps(result), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("APP绑定成功"))
        except HTTPException as exc:
            await r.set(key, json.dumps({"status": "error", "message": exc.detail}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg(str(exc.detail)))

    elif mode == "invite_player":
        owner_id = data.get("owner_id")
        if not owner_id:
            await r.set(key, json.dumps({"status": "error", "message": "缺少邀请人信息"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("缺少邀请人信息"))

        try:
            # 添加到常用打球人
            player, err = add_wechat_profile(
                db,
                owner_id,
                wechat_id,
                nickname=wx_info.get("nickname"),
                avatar_url=wx_info.get("avatar_url"),
            )
            if err:
                if err == "ALREADY_EXISTS":
                    pass
                elif err == "WECHAT_IS_MAIN_USER":
                    raise HTTPException(status_code=400, detail="该微信已绑定为主账号，无法添加")
                else:
                    raise HTTPException(status_code=400, detail="添加失败")

            result = {
                "status": "ready",
                "message": "添加常用打球人成功",
                "player": {
                    "name": player.name,
                    "avatar_url": player.avatar_url
                }
            }
            await r.set(key, json.dumps(result), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("添加常用打球人成功"))
        except HTTPException as exc:
            await r.set(key, json.dumps({"status": "error", "message": exc.detail}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg(str(exc.detail)))
        except Exception as e:
            logger.error(f"添加常用打球人失败: {e}")
            await r.set(key, json.dumps({"status": "error", "message": "添加失败"}), ex=WEB_QR_READY_TTL)
            return HTMLResponse(render_msg("添加失败"))

    else:
        return HTMLResponse(render_msg("未知模式"))


@router.get("/wechat-web/poll", response_model=QRLoginPollResponse)
async def wechat_web_poll(qr_token: str, mode: str, r=Depends(get_redis)):
    key = web_qr_key(mode, qr_token)
    val = await r.get(key)
    if not val:
        raise HTTPException(status_code=404, detail="二维码不存在或已过期")
    try:
        data = json.loads(val)
    except Exception:
        data = {}
    status = data.get("status")
    if status == "pending":
        return QRLoginPollResponse(status="pending")
    if status == "error":
        await r.delete(key)
        return QRLoginPollResponse(status="error", message=data.get("message"))
    if status == "ready":
        await r.delete(key)
        user_data = data.get("user", {})
        # 兼容 invite 模式返回的 member/player 信息
        member_data = data.get("member", {})
        player_data = data.get("player", {})

        # 如果是 invite 模式，可能没有 user_data，但有 member/player
        # 这里简单处理，将 member/player 的信息映射到 username/avatar_url
        username = user_data.get("username") or member_data.get("nickname") or player_data.get("name")
        avatar_url = user_data.get("avatar_url") or member_data.get("avatar_url") or player_data.get("avatar_url")

        return QRLoginPollResponse(
            status="ready",
            message=data.get("message"), # 成功消息
            access_token=data.get("access_token"),
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type") or "Bearer",
            expires_in=data.get("expires_in"),
            id=user_data.get("id"),
            telephone=user_data.get("telephone"),
            username=username,
            avatar_url=avatar_url,
            role=user_data.get("role"),
            unionid=user_data.get("unionid"),
        )
    if status == "error":
        await r.delete(key)
        raise HTTPException(status_code=400, detail=data.get("message") or "扫码失败")
    raise HTTPException(status_code=400, detail="二维码状态异常")
