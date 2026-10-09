from datetime import date
from pydantic import BaseModel, Field
from typing import List


class DayVideoSummary(BaseModel):
    """某天的打球视频数量"""
    date: date
    count: int


class DayVideoCountSummary(BaseModel):
    """某天可下载视频数量与本地已存在数量"""
    date: date
    count: int
    exist_count: int


class DayVideoListResponse(BaseModel):
    """按 owner 聚合的视频天数列表"""
    owner_id: str
    wechat_unionid: str | None = None
    items: List[DayVideoSummary]


class DayVideoCountResponse(BaseModel):
    owner_id: str
    wechat_unionid: str | None = None
    items: List[DayVideoCountSummary]


class DaysRequest(BaseModel):
    owner_id: str
    wechat_unionid: str | None = None


class DayCountRequest(BaseModel):
    owner_id: str
    wechat_unionid: str | None = None
    day: date
    videos_ids: List[str] = Field(default_factory=list)


class DownloadRequest(BaseModel):
    videos_ids: List[str] = Field(default_factory=list)


class CopyVideosRequest(BaseModel):
    videos_ids: List[str]


class CopyVideosResponse(BaseModel):
    message: str
    success_count: int
    skipped_count: int
    requested_total: int = 0
    paired_slave_total: int = 0
    paired_slave_success_count: int = 0
    paired_slave_skipped_count: int = 0
    paired_slave_has_success: bool = False


class DownloadVideoItem(BaseModel):
    video_id: str
    is_favorited: bool
    pair_session_id: str | None = None
    is_primary_video: bool = True


class DownloadFavoriteVideoItem(DownloadVideoItem):
    wechat_unionid: str | None = None


class DownloadResponse(BaseModel):
    video_urls: List[str]
    draw_urls: List[str]
    multi_draw_urls: List[str]
    total_videos: int
    items: List[DownloadVideoItem]


class DownloadFavoriteResponse(BaseModel):
    video_urls: List[str]
    draw_urls: List[str]
    multi_draw_urls: List[str]
    total_videos: int
    items: List[DownloadFavoriteVideoItem]
