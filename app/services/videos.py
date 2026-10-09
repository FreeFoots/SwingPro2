import os
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
from app.db.models.video import Video
from app.db.models.user import User, Player
from app.core.security import now_bj
from app.services.tasks import analyze_video_metadata
from app.core.config import settings
from app.services.video_processing import process_upload_file, ProcessedVideo

def save_video_file(upload_file) -> ProcessedVideo:
    """处理并保存上传文件，返回处理结果"""
    return process_upload_file(
        upload_file,
        video_root=settings.VIDEO_ROOT,
        thumb_root=settings.THUMB_ROOT,
        tmp_root=settings.VIDEO_TMP_ROOT,
    )

def create_video_record(
    db: Session,
    uploader_id: str,
    file_path: str,
    mime_type: str,
    size_bytes: int,
    view_type: int = 0,
    thumbnail_path: str | None = None,
    owner_id: str | None = None,
    photo_at: datetime | None = None,
    wechat_unionid: str | None = None,
    pair_session_id: str | None = None,
    is_primary_video: bool = True,
):
    """创建视频数据库记录"""
    created_time = now_bj()
    if not owner_id:
        owner_id = uploader_id
    video_name = os.path.basename(file_path)

    # 优先使用拍摄时间，若无则使用创建时间
    final_photo_at = photo_at or created_time

    video = Video(
        uploader_id=uploader_id,
        file_path=file_path,
        name=video_name,
        mime_type=mime_type,
        title=final_photo_at.strftime("%Y-%m-%d %H:%M:%S"),
        size_bytes=size_bytes,
        view_type=view_type,
        status="ready",
        created_at=created_time,
        photo_at=final_photo_at,
        thumb_path=thumbnail_path,
        owner_id=owner_id,
        wechat_unionid=wechat_unionid,
        pair_session_id=pair_session_id,
        is_primary_video=is_primary_video,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    # 异步任务：后台分析视频
    analyze_video_metadata.delay(video.id)

    return video


def paginate_videos(
    db: Session,
    *,
    owner_id: str | None,
    page: int,
    page_size: int,
    sort_by: str,
    sort_order: str,
    view_type: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
    status: str | None,
    search_keyword: str | None = None,
    filter_type: str | None = None,  # "user" or "wechat"
    user_keyword: str | None = None,
    wechat_keyword: str | None = None,
    is_favorited: bool | None = None,
    has_draw: bool | None = None,
    paired_only: bool | None = None,
    deleted_only: bool = False,
) -> dict[str, Any]:
    """通用的视频分页查询，供用户与管理员共享"""

    # 基础筛选
    if deleted_only:
        query = db.query(Video).filter(Video.deleted == True)  # noqa: E712
    else:
        query = db.query(Video).filter(Video.deleted == False)  # noqa: E712
    if owner_id:
        query = query.filter(Video.owner_id == owner_id)
    if view_type is not None:
        query = query.filter(Video.view_type == view_type)
    if is_favorited is not None:
        query = query.filter(Video.isFavorited == is_favorited)
    if status:
        query = query.filter(Video.status == status)
    if created_from:
        query = query.filter(Video.photo_at >= created_from)
    if created_to:
        query = query.filter(Video.photo_at <= created_to)
    if paired_only is True:
        query = query.filter(
            Video.pair_session_id.isnot(None),
            Video.pair_session_id != "",
            Video.is_primary_video == True,  # noqa: E712
        )
    if has_draw is True:
        query = query.filter(
            or_(
                and_(Video.drawed_path.isnot(None), Video.drawed_path != ""),
                and_(Video.multi_drawed_path.isnot(None), Video.multi_drawed_path != ""),
            )
        )
    elif has_draw is False:
        query = query.filter(
            or_(Video.drawed_path.is_(None), Video.drawed_path == ""),
            or_(Video.multi_drawed_path.is_(None), Video.multi_drawed_path == ""),
        )

    user_kw = user_keyword
    wechat_kw = wechat_keyword
    if search_keyword:
        if filter_type == "user" and not user_kw:
            user_kw = search_keyword
        elif filter_type == "wechat" and not wechat_kw:
            wechat_kw = search_keyword

    if user_kw:
        keyword = f"%{user_kw}%"
        # db.query 返回的是 tuple 用于 (User.id,)
        user_ids_rows = db.query(User.id).filter(
            (User.username.like(keyword)) | (User.telephone.like(keyword))
        ).all()
        user_ids = [row[0] for row in user_ids_rows]

        if user_ids:
            query = query.filter(Video.owner_id.in_(user_ids))
        else:
            # 搜不到用户则无结果
            query = query.filter(1 == 0)

    if wechat_kw:
        normalized = str(wechat_kw).strip().lower()
        if normalized in {"游客", "guest"}:
            # 游客定义：wechat_unionid 为空，或 unionid 在 players 表中没有映射资料。
            mapped_unionids = [
                row[0]
                for row in db.query(Player.wechat_unionid)
                .filter(Player.wechat_unionid.isnot(None), Player.wechat_unionid != "")
                .all()
            ]
            if mapped_unionids:
                query = query.filter(
                    or_(
                        Video.wechat_unionid.is_(None),
                        Video.wechat_unionid == "",
                        ~Video.wechat_unionid.in_(mapped_unionids),
                    )
                )
            else:
                query = query.filter(
                    or_(
                        Video.wechat_unionid.is_(None),
                        Video.wechat_unionid == "",
                    )
                )
        else:
            keyword = f"%{wechat_kw}%"
            # 微信模糊匹配：昵称大小写不敏感 + unionid 模糊匹配
            unionids_rows = (
                db.query(Player.wechat_unionid)
                .filter(
                    Player.wechat_unionid.isnot(None),
                    Player.wechat_unionid != "",
                    or_(
                        Player.name.ilike(keyword),
                        Player.wechat_unionid.ilike(keyword),
                    ),
                )
                .all()
            )
            unionids = [row[0] for row in unionids_rows if row and row[0]]

            if unionids:
                query = query.filter(Video.wechat_unionid.in_(unionids))
            else:
                # players 中无匹配时，退化为直接对视频 unionid 做模糊匹配
                query = query.filter(
                    Video.wechat_unionid.isnot(None),
                    Video.wechat_unionid != "",
                    Video.wechat_unionid.ilike(keyword),
                )

    # 总数
    total = query.with_entities(func.count()).scalar() or 0

    # 排序
    # Per user request: sort by photo_at even if "created_at" is requested
    sort_map = {
        "created_at": Video.created_at,
        "photo_at": Video.photo_at,
        "duration": Video.duration,
        "size_bytes": Video.size_bytes,
    }
    sort_column = sort_map.get(sort_by, Video.photo_at) # Default to photo_at
    if sort_order.lower() == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # 分页
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)
    items = (
        query.offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .all()
    )

    owner_profiles: dict[str, dict[str, Any]] = {}
    video_owner_ids: dict[int, list[str]] = {}
    wechat_profiles: dict[str, str] = {}
    wechat_user_profiles: dict[str, dict[str, Any]] = {}

    if items:
        all_owner_ids: set[str] = set()
        all_unionids: set[str] = set()

        for video in items:
            owner = video.owner_id
            ids = [owner] if owner else []
            video_owner_ids[video.id] = ids
            all_owner_ids.update(ids)
            if video.wechat_unionid:
                all_unionids.add(video.wechat_unionid)

        if all_owner_ids:
            rows = (
                db.query(User.id, User.username, User.telephone)
                .filter(User.id.in_(all_owner_ids))
                .all()
            )
            owner_profiles = {
                row[0]: {
                    "username": row[1],
                    "telephone": row[2],
                }
                for row in rows
            }

        if all_unionids:
            # 查找 Player 表获取微信名称
            # 既然 unionid 唯一对应一个人(大致上)，我们取最新的名称
            p_rows = (
                db.query(Player.wechat_unionid, Player.name, Player.avatar_url)
                .filter(Player.wechat_unionid.in_(all_unionids))
                .all()
            )
            # 简单的字典映射，如果有重名会覆盖，暂且接受
            wechat_profiles = {r[0]: r[1] for r in p_rows}
            wechat_user_profiles = {
                r[0]: {
                    "name": r[1],
                    "avatar_url": r[2],
                }
                for r in p_rows
            }

    return {
        "items": items,
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "owner_profiles": owner_profiles,
        "video_owner_ids": video_owner_ids,
        "wechat_profiles": wechat_profiles,
        "wechat_user_profiles": wechat_user_profiles,
    }
