from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Enum,
    BigInteger,
    Numeric,
)
from app.db.base import Base
from app.core.security import now_bj  # 统一北京时间


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uploader_id = Column(String(36), ForeignKey("app_user.id"), nullable=False)
    owner_id = Column(String(36), ForeignKey("app_user.id"), nullable=False, index=True)

    # 视频实际所属的微信用户
    wechat_unionid = Column(String(64), nullable=True, index=True)

    # 配对会话ID：同一ID代表同一组主从视频
    pair_session_id = Column(String(64), nullable=True, index=True)
    # 是否主视频。未参与配对时默认为主视频。
    is_primary_video = Column(Boolean, nullable=False, default=True)

    file_path = Column(Text, nullable=False)
    name = Column(String(255), nullable=True, index=True)
    mime_type = Column(String(64), nullable=False)
    title = Column(String(128), nullable=True)
    fps = Column(Numeric(6, 3), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    duration = Column(Integer, nullable=True)
    resolution = Column(String(32), nullable=True)

    status = Column(Enum("pending", "ready", "finished", "failed", name="video_status"), default="pending")

    created_at = Column(DateTime(timezone=True), default=now_bj)
    photo_at = Column(DateTime(timezone=True), nullable=True)
    thumb_path = Column(Text, nullable=True)
    view_type = Column(Integer, default=0)  # 0侧面、1正面、2专业、3俯视(top)、4其他(other)
    deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    isFavorited = Column(Boolean, default=False)
    frames_path = Column(Text, nullable=True)
    drawed_path = Column(Text, nullable=True)
    multi_drawed_path = Column(Text, nullable=True)
