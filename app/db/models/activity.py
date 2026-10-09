"""
业务统计数据模型

用于记录系统各类业务行为，支持管理后台查看和统计
"""

from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Text, Index, JSON
from app.db.base import Base
from app.core.security import now_bj


class ActivityLog(Base):
    """
    业务行为日志

    用于记录所有需要统计和审计的业务操作
    """
    __tablename__ = "activity_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=now_bj, index=True)

    # 行为分类
    category = Column(String(32), nullable=False, index=True, comment="分类: auth/video/user")
    action = Column(String(64), nullable=False, index=True, comment="具体行为")

    # 操作者
    user_id = Column(String(36), index=True, comment="操作用户ID")
    user_telephone = Column(String(20), comment="用户手机号(脱敏)")
    user_role = Column(String(20), comment="用户角色")

    # 操作对象
    target_type = Column(String(32), comment="目标类型: user/video/field等")
    target_id = Column(String(64), comment="目标ID")

    # 详情
    detail = Column(JSON, comment="详细信息JSON")

    # 请求信息
    ip_address = Column(String(45), comment="客户端IP")
    user_agent = Column(String(200), comment="客户端UA")

    # 结果
    success = Column(Integer, default=1, comment="是否成功: 1成功 0失败")
    error_msg = Column(String(500), comment="失败原因")

    __table_args__ = (
        Index('ix_activity_category_action', 'category', 'action'),
        Index('ix_activity_created_category', 'created_at', 'category'),
    )


# ============== 行为分类常量 ==============

class ActivityCategory:
    """行为分类"""
    AUTH = "auth"           # 认证相关
    VIDEO = "video"         # 视频相关
    USER = "user"           # 用户管理
    SYSTEM = "system"       # 系统操作


class ActivityAction:
    """具体行为"""
    # 认证类
    SEND_OTP = "send_otp"           # 发送验证码
    REGISTER = "register"           # 注册
    LOGIN = "login"                 # 登录
    LOGIN_WECHAT = "login_wechat"   # 微信登录
    LOGOUT = "logout"               # 登出
    BIND_WECHAT = "bind_wechat"     # 绑定微信

    # 视频类
    VIDEO_UPLOAD = "video_upload"   # 上传视频
    VIDEO_DELETE = "video_delete"   # 删除视频
    VIDEO_DOWNLOAD = "video_download" # 下载视频

    # 用户管理类（敏感）
    PASSWORD_CHANGE = "password_change"     # 修改密码
    PASSWORD_RESET = "password_reset"       # 重置密码
    ROLE_CHANGE = "role_change"             # 修改权限
    USER_DISABLE = "user_disable"           # 禁用用户
    USER_ENABLE = "user_enable"             # 启用用户

    # 邀请码类
    INVITE_CREATE = "invite_create"   # 创建邀请码
    INVITE_USE = "invite_use"         # 使用邀请码
