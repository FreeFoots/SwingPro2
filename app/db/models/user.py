import uuid
import enum
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Enum, DateTime, BigInteger, Text, Index
from sqlalchemy.sql import func
from app.db.base import Base

class RoleEnum(enum.Enum):
    user = "user"
    business = "business"
    admin = "admin"
    super_admin = "super_admin"
    system_admin = "system_admin"


class MemberTierEnum(enum.Enum):
    normal = "normal"
    plus = "plus"
    pro = "pro"
    ultra = "ultra"


class User(Base):
    __tablename__ = "app_user"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    telephone = Column(String(20), unique=True, nullable=False, index=True)
    password = Column(Text, nullable=True)  # 可空，支持仅验证码登录
    username = Column(String(50), nullable=True)
    avatar_url = Column(Text, nullable=True)
    role = Column(Enum(RoleEnum), default=RoleEnum.user)
    membership_tier = Column(String(16), nullable=True, default=MemberTierEnum.normal.value, server_default=MemberTierEnum.normal.value, index=True)
    status = Column(Boolean, default=True)
    disabled_until = Column(DateTime(timezone=True), nullable=True)
    refresh_token_ttl_days = Column(Integer, nullable=False, default=7)

    # 单端登录控制（app/web 各保持一个）
    app_session_id = Column(String(32), nullable=True)
    web_session_id = Column(String(32), nullable=True)
    device_id = Column(String(128), nullable=True, index=True)  # App 端设备唯一ID（用于重复登录判断）
    device_name = Column(String(128), nullable=True)  # App 端设备展示名（如 iPad Pro）

    # WeChat
    wechat_unionid = Column(String(64), unique=True, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    lastlogin_at = Column(DateTime(timezone=True), onupdate=func.now())

class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    secret_hash = Column(String(64), nullable=False)  # refresh_token 哈希
    token_id = Column(String(32), unique=True, index=True, nullable=False)
    client_type = Column(String(16), nullable=False, default="app")  # app | web
    revoked = Column(Boolean, default=False)
    rotated_from = Column(BigInteger, ForeignKey("refresh_token.id"), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Index("idx_refresh_user_revoked", RefreshToken.user_id, RefreshToken.revoked)

class InviteCode(Base):
    __tablename__ = "invite_code"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    status = Column(String(20), default="unused")  # unused / used / expired
    expired_at = Column(DateTime(timezone=True), nullable=True) # 过期时间
    duration_days = Column(Integer, nullable=False, default=30) # 使用时长（天）
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    created_id = Column(String(36), ForeignKey("app_user.id"), nullable=True)  # 管理员
    user_id = Column(String(36), ForeignKey("app_user.id"), nullable=True)     # 使用者
    telephone = Column(String(20), nullable=True)


# =========================
# 常用打球人表
# =========================
class Player(Base):
    """
    常用打球人表：系统用户的常用打球人列表
    - 一个微信用户可以是多个系统用户的常用打球人
    """
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(String(36), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)  # 所属系统用户
    wechat_unionid = Column(String(64), nullable=False, index=True)  # 微信 unionid
    name = Column(String(100), nullable=False)  # 显示名称
    avatar_url = Column(Text, nullable=True)  # 头像
    active = Column(Boolean, default=False)  # 是否当前选中打球人
    is_self = Column(Boolean, default=False)  # 是否为主账号绑定的微信
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("uq_players_owner_wechat", "owner_id", "wechat_unionid", unique=True),
    )


class RolePermissionPolicy(Base):
    """
    角色权限策略表
    - role: 角色
    - membership_tier: 会员等级（仅 user/business 时生效，可为空表示该角色通配）
    - permission_key: 权限点，例如 invite.create
    - allowed: 是否允许
    """
    __tablename__ = "role_permission_policy"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role = Column(Enum(RoleEnum), nullable=False, index=True)
    membership_tier = Column(String(16), nullable=True, index=True)
    permission_key = Column(String(64), nullable=False, index=True)
    allowed = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


Index(
    "idx_role_perm_lookup",
    RolePermissionPolicy.role,
    RolePermissionPolicy.membership_tier,
    RolePermissionPolicy.permission_key,
)


class RoleScopePolicy(Base):
    """
    角色分级权限策略表
    - role: 角色
    - membership_tier: 会员等级（仅 user/business 生效，可为空表示该角色通配）
    - scope_key: 权限域，例如 video/user/invite
    - max_level: 该域可用最高等级（0 表示无权限）
    """
    __tablename__ = "role_scope_policy"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role = Column(Enum(RoleEnum), nullable=False, index=True)
    membership_tier = Column(String(16), nullable=True, index=True)
    scope_key = Column(String(64), nullable=False, index=True)
    max_level = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


Index(
    "idx_role_scope_lookup",
    RoleScopePolicy.role,
    RoleScopePolicy.membership_tier,
    RoleScopePolicy.scope_key,
)
