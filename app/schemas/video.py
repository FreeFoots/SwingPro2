from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field

VIEW_TYPE_SIDE = 0
VIEW_TYPE_FRONT = 1
VIEW_TYPE_PRO = 2
VIEW_TYPE_TOP = 3
VIEW_TYPE_OTHER = 4

VALID_VIEW_TYPES = {
    VIEW_TYPE_SIDE,
    VIEW_TYPE_FRONT,
    VIEW_TYPE_PRO,
    VIEW_TYPE_TOP,
    VIEW_TYPE_OTHER,
}

class VideoOwnerInfo(BaseModel):
    user_id: str
    username: Optional[str] = None
    telephone: Optional[str] = None


class VideoOut(BaseModel):
    id: int
    title: Optional[str] = None
    file_path: str
    name: Optional[str] = None
    thumb_path: Optional[str] = None
    drawed_path: Optional[str] = None
    multi_drawed_path: Optional[str] = None
    file_url: Optional[str] = None
    thumb_url: Optional[str] = None
    mime_type: str
    status: str
    duration: Optional[int] = None
    fps: Optional[float] = None
    resolution: Optional[str] = None
    size_bytes: int
    view_type: int
    created_at: datetime
    photo_at: Optional[datetime] = None
    isFavorited: bool
    owner_id: Optional[str] = None
    owner_username: Optional[str] = None
    owner_telephone: Optional[str] = None
    owners: List[VideoOwnerInfo] = Field(default_factory=list)
    wechat_unionid: Optional[str] = None  # 视频实际所属的微信用户
    pair_session_id: Optional[str] = None
    is_primary_video: bool = True

    class Config:
        from_attributes = True


class VideoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[VideoOut]
    owner_profiles: dict[str, Any] = {}
    wechat_profiles: dict[str, str] = {}
    wechat_user_profiles: dict[str, Any] = {}


class VideoPlaybackItem(BaseModel):
    video: VideoOut
    draw_json: dict[str, Any] | None = None
    multi_draw_json: dict[str, Any] | None = None


class VideoPlaybackResponse(BaseModel):
    video: VideoOut
    draw_json: dict[str, Any] | None = None
    multi_draw_json: dict[str, Any] | None = None
    videos: List[VideoPlaybackItem] = Field(default_factory=list)


class VideoSummaryByType(BaseModel):
    view_type: int
    count: int


class VideoSummaryByUser(BaseModel):
    user_id: str
    username: Optional[str] = None
    telephone: Optional[str] = None
    count: int


class VideoSummaryResponse(BaseModel):
    by_view_type: List[VideoSummaryByType]
    by_user: List[VideoSummaryByUser]


class VideosAppDeleteRequest(BaseModel):
    videos_ids: List[str]


class VideoBatchDownloadRequest(BaseModel):
    video_ids: List[int] = Field(default_factory=list)


class VideoBatchDownloadResponse(BaseModel):
    download_urls: List[str]
    total_videos: int
    missing_ids: List[int] = Field(default_factory=list)


class VideoFavoriteBatchRequest(BaseModel):
    favorite_video_ids: List[str] = Field(default_factory=list)
    unfavorite_video_ids: List[str] = Field(default_factory=list)


class VideoFavoriteBatchResponse(BaseModel):
    ok: bool = True
    updated_favorite: int
    updated_unfavorite: int
    updated_total: int


class VideoDrawJsonPayload(BaseModel):
    video_id: str
    draw_json: dict[str, Any]
    multi_draw_json: dict[str, Any] = Field(default_factory=dict)
