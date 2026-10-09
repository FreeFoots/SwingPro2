"""
行为记录辅助函数

简化在 API 中记录业务行为的操作
"""

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.activity import ActivityCategory, ActivityAction
from app.services.activity import log_activity


def get_client_info(request: Request) -> tuple[str, str]:
    """从请求中获取客户端信息"""
    # IP
    ip = request.headers.get("x-forwarded-for")
    if ip:
        ip = ip.split(",")[0].strip()
    else:
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)

    # UA
    ua = request.headers.get("user-agent", "")

    return ip, ua


# ============== 认证类 ==============

def log_send_otp(db: Session, request: Request, telephone: str, success: bool = True, error: str = None):
    """记录发送验证码"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.AUTH,
        action=ActivityAction.SEND_OTP,
        user_telephone=telephone,
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_register(db: Session, request: Request, user: User, success: bool = True, error: str = None):
    """记录注册"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.AUTH,
        action=ActivityAction.REGISTER,
        user_id=user.id if user else None,
        user_telephone=user.telephone if user else None,
        target_type="user",
        target_id=user.id if user else None,
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_login(
    db: Session,
    request: Request,
    user: User,
    method: str = "password",
    client_type: str = "app",
    success: bool = True,
    error: str = None,
):
    """记录登录"""
    ip, ua = get_client_info(request)
    action = ActivityAction.LOGIN_WECHAT if method == "wechat" else ActivityAction.LOGIN
    log_activity(
        db,
        category=ActivityCategory.AUTH,
        action=action,
        user_id=user.id if user else None,
        user_telephone=user.telephone if user else None,
        user_role=user.role.value if user and user.role else None,
        detail={"method": method, "client_type": client_type},
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_bind_wechat(db: Session, request: Request, user: User, unionid: str, success: bool = True, error: str = None):
    """记录绑定微信"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.AUTH,
        action=ActivityAction.BIND_WECHAT,
        user_id=user.id,
        user_telephone=user.telephone,
        detail={"unionid": unionid[:8] + "***" if unionid else None},
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


# ============== 视频类 ==============

def log_video_upload(db: Session, request: Request, user: User, video_id: int, file_size: int = None, success: bool = True, error: str = None):
    """记录视频上传"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.VIDEO,
        action=ActivityAction.VIDEO_UPLOAD,
        user_id=user.id,
        user_telephone=user.telephone,
        user_role=user.role.value if user.role else None,
        target_type="video",
        target_id=str(video_id) if video_id else None,
        detail={"size_bytes": file_size} if file_size else None,
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_video_delete(db: Session, request: Request, user: User, video_id: int, success: bool = True, error: str = None):
    """记录视频删除"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.VIDEO,
        action=ActivityAction.VIDEO_DELETE,
        user_id=user.id,
        user_telephone=user.telephone,
        user_role=user.role.value if user.role else None,
        target_type="video",
        target_id=str(video_id),
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


# ============== 用户管理类（敏感）==============

def log_password_change(db: Session, request: Request, user: User, target_user: User = None, success: bool = True, error: str = None):
    """记录修改密码"""
    ip, ua = get_client_info(request)
    target = target_user or user
    log_activity(
        db,
        category=ActivityCategory.USER,
        action=ActivityAction.PASSWORD_CHANGE,
        user_id=user.id,
        user_telephone=user.telephone,
        user_role=user.role.value if user.role else None,
        target_type="user",
        target_id=target.id,
        detail={"target_telephone": target.telephone[:3] + "****" + target.telephone[-4:] if target.telephone else None},
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_role_change(db: Session, request: Request, operator: User, target_user: User, old_role: str, new_role: str, success: bool = True, error: str = None):
    """记录修改权限"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.USER,
        action=ActivityAction.ROLE_CHANGE,
        user_id=operator.id,
        user_telephone=operator.telephone,
        user_role=operator.role.value if operator.role else None,
        target_type="user",
        target_id=target_user.id,
        detail={
            "target_telephone": target_user.telephone[:3] + "****" + target_user.telephone[-4:] if target_user.telephone else None,
            "old_role": old_role,
            "new_role": new_role,
        },
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


def log_user_status_change(db: Session, request: Request, operator: User, target_user: User, enabled: bool, success: bool = True, error: str = None):
    """记录启用/禁用用户"""
    ip, ua = get_client_info(request)
    action = ActivityAction.USER_ENABLE if enabled else ActivityAction.USER_DISABLE
    log_activity(
        db,
        category=ActivityCategory.USER,
        action=action,
        user_id=operator.id,
        user_telephone=operator.telephone,
        user_role=operator.role.value if operator.role else None,
        target_type="user",
        target_id=target_user.id,
        detail={"target_telephone": target_user.telephone[:3] + "****" + target_user.telephone[-4:] if target_user.telephone else None},
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )


# ============== 场地管理类（敏感）==============



# ============== 邀请码类 ==============

def log_invite_create(db: Session, request: Request, user: User, invite_code: str, success: bool = True, error: str = None):
    """记录创建邀请码"""
    ip, ua = get_client_info(request)
    log_activity(
        db,
        category=ActivityCategory.AUTH,
        action=ActivityAction.INVITE_CREATE,
        user_id=user.id,
        user_telephone=user.telephone,
        user_role=user.role.value if user.role else None,
        target_type="invite",
        target_id=invite_code,
        ip_address=ip,
        user_agent=ua,
        success=success,
        error_msg=error,
    )
