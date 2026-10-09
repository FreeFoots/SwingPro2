import os
import json
import uuid
import zipfile
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, Form, File, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from collections import Counter

from app.core.deps import get_db, get_current_user, role_at_least, require_scope
from app.core.security import now_bj
from app.schemas.video import (
    VideoOut,
    VideoListResponse,
    VideoPlaybackItem,
    VideoPlaybackResponse,
    VideoSummaryResponse,
    VideoSummaryByType,
    VideoSummaryByUser,
    VideosAppDeleteRequest,
    VideoBatchDownloadRequest,
    VideoBatchDownloadResponse,
    VideoFavoriteBatchRequest,
    VideoFavoriteBatchResponse,
    VideoDrawJsonPayload,
    VALID_VIEW_TYPES,
)
from app.services.videos import save_video_file, create_video_record, paginate_videos
from app.db.models.user import User, RoleEnum
from app.db.models.video import Video
from app.core.config import settings
from app.services.activity_helper import log_video_upload, log_video_delete
from app.services.video_processing import normalize_filename, TARGET_EXT


router = APIRouter()
logger = logging.getLogger(__name__)


def primary_owner_id(video: Video) -> str | None:
    return video.owner_id or video.uploader_id


def _normalize_pair_session_id(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.lower() == "null":
        return None
    return text


def _pair_session_lookup_key(value: str | None) -> str | None:
    sid = _normalize_pair_session_id(value)
    if not sid:
        return None
    return sid.lower()


def _is_primary_video_true(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "t", "yes", "y"}


def _is_primary_video_false(value) -> bool:
    if isinstance(value, bool):
        return not value
    text = str(value or "").strip().lower()
    return text in {"false", "0", "f", "no", "n"}


def ensure_view_type_valid(view_type: int | None) -> None:
    if view_type is None:
        return
    if view_type not in VALID_VIEW_TYPES:
        raise HTTPException(status_code=400, detail="无效的视频分类，允许值为 0,1,2,3,4")


def save_draw_json(video: Video, draw_json: dict, is_multi: bool = False) -> str:
    now = now_bj()
    safe_owner = "".join(ch if ch.isalnum() else "_" for ch in str(primary_owner_id(video) or "unknown"))[:64]
    rel_dir = os.path.join(safe_owner, f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}")
    abs_dir = os.path.join(settings.DRAW_JSON_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    src_name = str(video.file_path or video.name or f"video_{video.id}").strip()
    src_base = os.path.basename(src_name)
    src_stem, _ = os.path.splitext(src_base)
    if not src_stem:
        src_stem = f"video_{video.id}"
    file_name = f"multi_{src_stem}.json" if is_multi else f"{src_stem}.json"

    abs_path = os.path.join(abs_dir, file_name)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(draw_json, f, ensure_ascii=False)
    if is_multi:
        video.multi_drawed_path = abs_path
    else:
        video.drawed_path = abs_path
    return abs_path


def read_draw_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Failed to read draw json %s: %s", path, exc)
        return None


def _get_base_url(req: Request) -> str:
    if settings.WEB_PLATFORM_URL:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(settings.WEB_PLATFORM_URL)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass
    return str(req.base_url).rstrip('/')


def _add_video_paths_to_zip(archive: zipfile.ZipFile, videos: list[Video]) -> int:
    count = 0
    existing_names: set[str] = set()
    for video in videos:
        file_path = video.file_path
        if not file_path or not os.path.exists(file_path):
            continue
        base = os.path.basename(file_path)
        name, ext = os.path.splitext(base)
        candidate = base
        index = 1
        while candidate in existing_names:
            candidate = f"{name}_{index}{ext}"
            index += 1
        archive.write(file_path, arcname=candidate)
        existing_names.add(candidate)
        count += 1
    return count

# 上传视频
@router.post("/upload", response_model=VideoOut)
async def upload_video(
    request: Request,
    view_type: int = Form(...),
    wechat_unionid: str | None = Form(None, description="视频实际所属的微信用户 unionid"),
    pair_session_id: str | None = Form(None, description="配对会话ID，同一ID视为一组主从视频"),
    is_primary_video: bool = Form(True, description="是否主视频（同组中仅主视频为true）"),
    file: UploadFile = File(...),
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    ensure_view_type_valid(view_type)
    uploader = current_user
    wechat_unionid = None if wechat_unionid in (None, "", "null") else wechat_unionid
    pair_session_id = (pair_session_id or "").strip() or None
    if pair_session_id and str(pair_session_id).lower() == "null":
        pair_session_id = None
    # 未参与配对时，统一视为主视频。
    is_primary_video = bool(is_primary_video) if pair_session_id else True

    normalized_name, _ = normalize_filename(file.filename or "")
    target_filename = f"{normalized_name}{TARGET_EXT}"
    base_query = db.query(Video).filter(Video.file_path.like(f"%/{target_filename}"))

    # 情况1/2：上传者与 unionid 均一致
    same_uploader_union = (
        base_query
        .filter(
            Video.uploader_id == uploader.id,
            Video.wechat_unionid == wechat_unionid,
        )
        .order_by(Video.created_at.desc())
        .first()
    )
    if same_uploader_union:
        changed = False
        if same_uploader_union.pair_session_id != pair_session_id:
            same_uploader_union.pair_session_id = pair_session_id
            changed = True
        if bool(same_uploader_union.is_primary_video) != is_primary_video:
            same_uploader_union.is_primary_video = is_primary_video
            changed = True

        exist_owner = db.query(User).filter(User.id == same_uploader_union.owner_id).first()
        owner_data = {}
        owners_list = []
        if exist_owner:
            owner_data = {
                "username": exist_owner.username,
                "telephone": exist_owner.telephone,
            }
            owners_list = [{"user_id": exist_owner.id, **owner_data}]

        if not same_uploader_union.deleted:
            if changed:
                db.commit()
                db.refresh(same_uploader_union)
            return to_video_out(
                same_uploader_union,
                request,
                owner=owner_data,
                owner_id=same_uploader_union.owner_id,
                owners=owners_list,
        )

        same_uploader_union.deleted = False
        same_uploader_union.deleted_at = None
        same_uploader_union.created_at = now_bj()
        same_uploader_union.pair_session_id = pair_session_id
        same_uploader_union.is_primary_video = is_primary_video
        db.commit()
        db.refresh(same_uploader_union)

        log_video_upload(
            db,
            request,
            uploader,
            same_uploader_union.id,
            file_size=same_uploader_union.size_bytes,
            success=True,
        )
        return to_video_out(
            same_uploader_union,
            request,
            owner=owner_data,
            owner_id=same_uploader_union.owner_id,
            owners=owners_list,
        )

    # 情况3：上传者或 unionid 与之前一致，复用原文件记录
    match_conditions = [Video.uploader_id == uploader.id]
    if wechat_unionid is not None:
        match_conditions.append(Video.wechat_unionid == wechat_unionid)
    match_any = (
        base_query
        .filter(or_(*match_conditions))
        .order_by(Video.created_at.desc())
        .first()
    )
    if match_any and match_any.file_path and os.path.exists(match_any.file_path):
        new_video = Video(
            uploader_id=uploader.id,
            owner_id=uploader.id,
            wechat_unionid=wechat_unionid,
            file_path=match_any.file_path,
            name=match_any.name,
            thumb_path=match_any.thumb_path,
            mime_type=match_any.mime_type,
            title=match_any.title,
            fps=match_any.fps,
            size_bytes=match_any.size_bytes,
            duration=match_any.duration,
            resolution=match_any.resolution,
            status=match_any.status,
            created_at=now_bj(),
            photo_at=match_any.photo_at,
            view_type=view_type,
            deleted=False,
            deleted_at=None,
            isFavorited=False,
            frames_path=match_any.frames_path,
            drawed_path=match_any.drawed_path,
            pair_session_id=pair_session_id,
            is_primary_video=is_primary_video,
        )
        db.add(new_video)
        db.commit()
        db.refresh(new_video)

        owner_profiles = {
            uploader.id: {
                "username": uploader.username,
                "telephone": uploader.telephone,
            }
        }
        owners_info = [
            {
                "user_id": uploader.id,
                "username": uploader.username,
                "telephone": uploader.telephone,
            }
        ]

        log_video_upload(db, request, uploader, new_video.id, file_size=new_video.size_bytes, success=True)

        return to_video_out(
            new_video,
            request,
            owner_profiles.get(uploader.id),
            uploader.id,
            owners_info,
        )

    owner_id = uploader.id
    owner_record = uploader

    processed = save_video_file(file)
    file_path = processed.video_path
    size = processed.size_bytes
    mime_type = processed.mime_type

    video = create_video_record(
        db=db,
        uploader_id=uploader.id,
        file_path=file_path,
        mime_type=mime_type,
        size_bytes=size,
        view_type=view_type,
        thumbnail_path=processed.thumbnail_path,
        owner_id=owner_id,
        photo_at=processed.captured_at,
        wechat_unionid=wechat_unionid,
        pair_session_id=pair_session_id,
        is_primary_video=is_primary_video,
    )
    owner_profiles = {
        owner_id: {
            "username": owner_record.username,
            "telephone": owner_record.telephone,
        }
    }
    owners_info = [
        {
            "user_id": owner_id,
            "username": owner_record.username,
            "telephone": owner_record.telephone,
        }
    ]

    # 记录视频上传
    log_video_upload(db, request, uploader, video.id, file_size=size, success=True)

    return to_video_out(
        video,
        request,
        owner_profiles.get(owner_id),
        owner_id,
        owners_info,
    )

# 用户视频列表（仅本人或管理员可看）
@router.get("/user/{user_id}", response_model=VideoListResponse)
def list_user_videos(
    request: Request,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    view_type: int | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    is_favorited: bool | None = None,
    has_draw: bool | None = None,
    paired_only: bool | None = None,
    deleted_only: bool = False,
    search_keyword: str | None = None,
    filter_type: str | None = None,
    user_keyword: str | None = None,
    wechat_keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_view_type_valid(view_type)
    viewer = current_user
    if viewer.id != user_id and not role_at_least(viewer.role, RoleEnum.admin):
        raise HTTPException(status_code=403, detail="无权查看他人视频")

    page_data = paginate_videos(
        db,
        owner_id=user_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        view_type=view_type,
        created_from=created_from,
        created_to=created_to,
        is_favorited=is_favorited,
        has_draw=has_draw,
        paired_only=paired_only,
        status=status,
        search_keyword=search_keyword,
        filter_type=filter_type,
        user_keyword=user_keyword,
        wechat_keyword=wechat_keyword,
        deleted_only=deleted_only,
    )
    return transform_page(page_data, request)


# 管理员视频列表（可筛选全部）
@router.get("/admin", response_model=VideoListResponse)
def list_all_videos(
    request: Request,
    owner_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    view_type: int | None = None,
    status: str | None = "finished",
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    is_favorited: bool | None = None,
    has_draw: bool | None = None,
    paired_only: bool | None = None,
    deleted_only: bool = False,
    search_keyword: str | None = None,
    filter_type: str | None = None,
    user_keyword: str | None = None,
    wechat_keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope("video", 3)),
):
    ensure_view_type_valid(view_type)
    page_data = paginate_videos(
        db,
        owner_id=owner_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        view_type=view_type,
        created_from=created_from,
        created_to=created_to,
        is_favorited=is_favorited,
        has_draw=has_draw,
        paired_only=paired_only,
        status=status,
        search_keyword=search_keyword,
        filter_type=filter_type,
        user_keyword=user_keyword,
        wechat_keyword=wechat_keyword,
        deleted_only=deleted_only,
    )
    return transform_page(page_data, request)


@router.get("/web/{video_id}/play", response_model=VideoPlaybackResponse)
def get_video_playback(
    request: Request,
    video_id: int,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    video = db.get(Video, video_id)
    if not video or video.deleted:
        raise HTTPException(status_code=404, detail="视频不存在")

    owner_id = primary_owner_id(video) or video.uploader_id
    if current_user.id != owner_id and not role_at_least(current_user.role, RoleEnum.admin):
        raise HTTPException(status_code=403, detail="无权查看该视频")

    owner = db.get(User, owner_id) if owner_id else None
    owner_info = (
        {
            "user_id": owner.id,
            "username": owner.username,
            "telephone": owner.telephone,
        }
        if owner
        else None
    )
    owners = [owner_info] if owner_info else []

    playback_videos = [video]
    sid = _normalize_pair_session_id(video.pair_session_id)
    if sid and _is_primary_video_true(video.is_primary_video):
        pair_expr = func.lower(func.btrim(Video.pair_session_id))
        siblings = (
            db.query(Video)
            .filter(
                Video.deleted == False,  # noqa: E712
                Video.pair_session_id.isnot(None),
                Video.pair_session_id != "",
                pair_expr == sid.strip().lower(),
                Video.id != video.id,
            )
            .order_by(Video.is_primary_video.desc(), Video.created_at.asc(), Video.id.asc())
            .all()
        )
        playback_videos.extend(siblings)

    playback_items: list[VideoPlaybackItem] = []
    for item in playback_videos:
        item_owner_id = primary_owner_id(item) or item.uploader_id
        item_owner_info = owner_info if item_owner_id == owner_id else None
        item_owners = owners if item_owner_id == owner_id else []
        playback_items.append(
            VideoPlaybackItem(
                video=to_video_out(item, request, item_owner_info, item_owner_id, item_owners),
                draw_json=read_draw_json(item.drawed_path),
                multi_draw_json=read_draw_json(item.multi_drawed_path),
            )
        )

    first_item = playback_items[0]
    return VideoPlaybackResponse(
        video=first_item.video,
        draw_json=first_item.draw_json,
        multi_draw_json=first_item.multi_draw_json,
        videos=playback_items,
    )




@router.get("/admin/summary", response_model=VideoSummaryResponse)
def admin_video_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope("video", 3)),
):
    by_type_rows = (
        db.query(Video.view_type, func.count(Video.id))
        .filter(Video.deleted == False)
        .group_by(Video.view_type)
        .order_by(Video.view_type.asc())
        .all()
    )
    by_type = [VideoSummaryByType(view_type=row[0], count=row[1]) for row in by_type_rows]

    videos = db.query(Video.owner_id).filter(Video.deleted == False).all()
    counter: Counter[str] = Counter()
    for (owner_id,) in videos:
        if owner_id:
            counter[str(owner_id)] += 1

    from app.db.models.user import User as UserModel

    if counter:
        user_rows = (
            db.query(UserModel.id, UserModel.username, UserModel.telephone)
            .filter(UserModel.id.in_(counter.keys()))
            .all()
        )
        user_map = {row[0]: (row[1], row[2]) for row in user_rows}
    else:
        user_map = {}

    by_user = [
        VideoSummaryByUser(
            user_id=user_id,
            username=(user_map.get(user_id) or (None, None))[0],
            telephone=(user_map.get(user_id) or (None, None))[1],
            count=count,
        )
        for user_id, count in counter.most_common()
    ]

    return VideoSummaryResponse(by_view_type=by_type, by_user=by_user)

# 软删除（仅本人或管理员）
@router.delete("/web/{video_id}")
def delete_video_web(
    request: Request,
    video_id: int,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    viewer = current_user
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    owner_id = primary_owner_id(video)
    if owner_id is None:
        owner_id = video.uploader_id
    if viewer.id != owner_id and not role_at_least(viewer.role, RoleEnum.admin):
        raise HTTPException(status_code=403, detail="无权删除他人视频")

    video.deleted = True
    video.deleted_at = now_bj()
    db.commit()

    # 记录视频删除
    log_video_delete(db, request, viewer, video_id, success=True)

    return {"ok": True, "msg": "视频已移入回收站"}


@router.delete("/app")
def delete_videos_app(
    request: Request,
    payload: VideosAppDeleteRequest,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    if not payload.videos_ids:
        raise HTTPException(status_code=400, detail="请提供要删除的视频名称")

    video_names = [name.strip() for name in payload.videos_ids if name and str(name).strip()]
    if not video_names:
        raise HTTPException(status_code=400, detail="请提供要删除的视频名称")

    videos = (
        db.query(Video)
        .filter(
            Video.name.in_(video_names),
            Video.owner_id == current_user.id,
            Video.deleted == False,  # noqa: E712
        )
        .all()
    )
    if not videos:
        raise HTTPException(status_code=404, detail="未找到可删除的视频")

    found_names = {video.name for video in videos if video.name}
    missing = [name for name in video_names if name not in found_names]
    if missing:
        raise HTTPException(status_code=404, detail=f"视频不存在: {', '.join(missing)}")

    primary_sessions_to_detach: set[str] = set()
    for video in videos:
        sid_key = _pair_session_lookup_key(video.pair_session_id)
        if sid_key and _is_primary_video_true(video.is_primary_video):
            primary_sessions_to_detach.add(sid_key)

        video.deleted = True
        video.deleted_at = now_bj()
        log_video_delete(db, request, current_user, video.id, success=True)

    if primary_sessions_to_detach:
        pair_expr = func.lower(func.btrim(Video.pair_session_id))
        slave_candidates = (
            db.query(Video)
            .filter(
                Video.deleted == False,  # noqa: E712
                Video.pair_session_id.isnot(None),
                pair_expr.in_(list(primary_sessions_to_detach)),
            )
            .all()
        )
        detached_count = 0
        for slave in slave_candidates:
            if not _is_primary_video_false(slave.is_primary_video):
                continue
            slave.pair_session_id = None
            detached_count += 1
        logger.debug(
            "DEBUG: /videos/app detach pair session after primary delete - sessions=%s detached_slaves=%s",
            sorted(primary_sessions_to_detach),
            detached_count,
        )

    db.commit()
    return {"ok": True, "deleted": len(videos)}


@router.post("/batch-download", response_model=VideoBatchDownloadResponse)
def batch_download_videos(
    request: Request,
    payload: VideoBatchDownloadRequest,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    ids = sorted(set(int(v) for v in payload.video_ids if int(v) > 0))
    if not ids:
        raise HTTPException(status_code=400, detail="请提供要下载的视频ID列表")

    query = db.query(Video).filter(Video.id.in_(ids), Video.deleted == False)
    if not role_at_least(current_user.role, RoleEnum.admin):
        query = query.filter(Video.owner_id == current_user.id)
    videos = query.order_by(Video.created_at.desc(), Video.id.desc()).all()

    found_ids = {v.id for v in videos}
    missing_ids = [v for v in ids if v not in found_ids]
    if not videos:
        raise HTTPException(status_code=404, detail="未找到可下载的视频")

    os.makedirs(settings.VIDEO_TMP_ROOT, exist_ok=True)
    safe_user = "".join(ch if ch.isalnum() else "_" for ch in str(current_user.id))[:32]
    stamp = now_bj().strftime("%Y%m%d_%H%M%S")
    zip_name = f"batch_{safe_user}_{stamp}_{uuid.uuid4().hex[:8]}.zip"
    zip_path = os.path.join(settings.VIDEO_TMP_ROOT, zip_name)
    tmp_path = zip_path + ".tmp"

    added = 0
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            added = _add_video_paths_to_zip(archive, videos)
        if added == 0:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise HTTPException(status_code=404, detail="所选视频文件不存在，无法打包")
        os.rename(tmp_path, zip_path)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"打包失败: {e}")

    base_url = _get_base_url(request)
    return VideoBatchDownloadResponse(
        download_urls=[f"{base_url}/download_temp/{zip_name}"],
        total_videos=added,
        missing_ids=missing_ids,
    )


@router.post("/favorite", response_model=VideoFavoriteBatchResponse)
def batch_set_favorite(
    payload: VideoFavoriteBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    favorite_names = [str(v).strip() for v in payload.favorite_video_ids if str(v).strip()]
    unfavorite_names = [str(v).strip() for v in payload.unfavorite_video_ids if str(v).strip()]
    if not favorite_names and not unfavorite_names:
        raise HTTPException(status_code=400, detail="请提供要收藏或取消收藏的视频名列表")

    # 同一个数组中重复出现同一视频，判定为无效请求。
    dup_favorite = sorted({name for name in favorite_names if favorite_names.count(name) > 1})
    dup_unfavorite = sorted({name for name in unfavorite_names if unfavorite_names.count(name) > 1})
    if dup_favorite:
        raise HTTPException(status_code=400, detail=f"favorite_video_ids存在重复视频: {dup_favorite[:20]}")
    if dup_unfavorite:
        raise HTTPException(status_code=400, detail=f"unfavorite_video_ids存在重复视频: {dup_unfavorite[:20]}")

    # 两个数组同时出现的同一视频，按“保持不变”处理。
    overlap = set(favorite_names).intersection(unfavorite_names)
    favorite_set = set(favorite_names) - overlap
    unfavorite_set = set(unfavorite_names) - overlap

    all_names = sorted(favorite_set.union(unfavorite_set))
    if len(all_names) > 500:
        raise HTTPException(status_code=400, detail="单次最多操作500个视频")

    if not all_names:
        return VideoFavoriteBatchResponse(updated_favorite=0, updated_unfavorite=0, updated_total=0)

    videos = (
        db.query(Video)
        .filter(
            Video.name.in_(all_names),
            Video.owner_id == current_user.id,
            Video.deleted == False,
        )
        .all()
    )

    found_names = {str(v.name) for v in videos if v.name}
    missing = [name for name in all_names if name not in found_names]
    if missing:
        raise HTTPException(status_code=404, detail=f"部分视频不存在或无权限: {missing[:20]}")

    updated_favorite = 0
    updated_unfavorite = 0

    for video in videos:
        if video.name in favorite_set:
            video.isFavorited = True
            updated_favorite += 1
        elif video.name in unfavorite_set:
            video.isFavorited = False
            updated_unfavorite += 1

    db.commit()
    return VideoFavoriteBatchResponse(
        updated_favorite=updated_favorite,
        updated_unfavorite=updated_unfavorite,
        updated_total=updated_favorite + updated_unfavorite,
    )


@router.post("/draw-json")
async def upload_draw_json_batch(
    payload: list[VideoDrawJsonPayload],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload:
        raise HTTPException(status_code=400, detail="请求体不能为空")
    if len(payload) > 200:
        raise HTTPException(status_code=400, detail="单次最多提交200条画线数据")

    video_names = list(dict.fromkeys(str(item.video_id).strip() for item in payload if str(item.video_id).strip()))
    if len(video_names) != len(payload):
        raise HTTPException(status_code=400, detail="video_id不能为空")

    videos = (
        db.query(Video)
        .filter(
            Video.name.in_(video_names),
            Video.owner_id == current_user.id,
            Video.deleted == False,  # noqa: E712
        )
        .order_by(Video.id.asc())
        .all()
    )

    video_map = {}
    for video in videos:
        if video.name and video.name not in video_map:
            video_map[video.name] = video

    missing = [name for name in video_names if name not in video_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"部分视频不存在: {missing[:20]}")

    result = []
    for item in payload:
        video_name = str(item.video_id).strip()
        video = video_map[video_name]
        owner_id = primary_owner_id(video) or video.uploader_id
        if current_user.id != owner_id and not role_at_least(current_user.role, RoleEnum.admin):
            raise HTTPException(status_code=403, detail=f"无权操作视频 {video_name}")
        abs_path = save_draw_json(video, item.draw_json)
        item_result = {"video_id": video.name, "drawed_path": abs_path}

        multi_draw_json = item.multi_draw_json or {}
        if multi_draw_json:
            multi_abs_path = save_draw_json(video, multi_draw_json, is_multi=True)
            item_result["multi_drawed_path"] = multi_abs_path

        result.append(item_result)

    db.commit()
    return {"ok": True, "updated": len(result), "items": result}


def to_video_out(
    video: Video,
    request: Request,
    owner: dict | None = None,
    owner_id: str | None = None,
    owners: list[dict] | None = None,
) -> VideoOut:
    file_url = build_media_url(video.file_path, request, is_thumb=False)
    thumb_url = build_media_url(video.thumb_path, request, is_thumb=True)
    fps = None
    if video.fps is not None:
        try:
            fps = float(video.fps)
        except (TypeError, ValueError):
            fps = None

    primary = owner_id or primary_owner_id(video)
    owner_info = owner or {}
    if primary and not owner_info and owners:
        owner_info = next((o for o in owners if o.get("user_id") == primary), {})

    return VideoOut(
        id=video.id,
        title=video.title,
        file_path=video.file_path,
        name=video.name or os.path.basename(video.file_path),
        thumb_path=video.thumb_path,
        drawed_path=video.drawed_path,
        multi_drawed_path=video.multi_drawed_path,
        file_url=file_url,
        thumb_url=thumb_url,
        mime_type=video.mime_type,
        status=video.status,
        duration=video.duration,
        fps=fps,
        resolution=video.resolution,
        size_bytes=video.size_bytes,
        view_type=video.view_type,
        created_at=video.created_at,
        photo_at=video.photo_at,
        isFavorited=video.isFavorited,
        owner_id=primary,
        owner_username=owner_info.get("username"),
        owner_telephone=owner_info.get("telephone"),
        owners=owners or [],
        wechat_unionid=video.wechat_unionid,
        pair_session_id=video.pair_session_id,
        is_primary_video=bool(video.is_primary_video),
    )


def transform_page(page_data: dict, request: Request) -> VideoListResponse:
    owner_profiles = page_data.get("owner_profiles") or {}
    video_owner_ids = page_data.get("video_owner_ids") or {}
    items = []
    for video in page_data["items"]:
        ids = video_owner_ids.get(video.id, [])
        owners_info = []
        for uid in ids:
            profile = owner_profiles.get(uid) or {}
            owners_info.append(
                {
                    "user_id": uid,
                    "username": profile.get("username"),
                    "telephone": profile.get("telephone"),
                }
            )
        primary = ids[0] if ids else primary_owner_id(video)
        items.append(
            to_video_out(
                video,
                request,
                owner_profiles.get(primary) if primary else None,
                primary,
                owners_info,
            )
        )
    return VideoListResponse(
        total=page_data["total"],
        page=page_data["page"],
        page_size=page_data["page_size"],
        items=items,
        owner_profiles=owner_profiles,
        wechat_profiles=page_data.get("wechat_profiles") or {},
        wechat_user_profiles=page_data.get("wechat_user_profiles") or {},
    )


def build_media_url(path: str | None, request: Request, is_thumb: bool = False) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path

    # 判断是缩略图还是视频
    thumb_root = settings.THUMB_ROOT.rstrip("/")
    video_root = settings.VIDEO_ROOT.rstrip("/")

    rel_path = None
    mount_point = ""

    # 如果路径包含 thumbs 目录或显式指定为缩略图
    if is_thumb or "/thumbs/" in path or path.startswith(thumb_root):
        try:
            rel_path = os.path.relpath(path, thumb_root)
            mount_point = "/thumbs"
        except ValueError:
            return None
    else:
        try:
            rel_path = os.path.relpath(path, video_root)
            mount_point = "/media"
        except ValueError:
            return None

    if not rel_path or rel_path.startswith(".."):
        return None

    # 转换为相对 URL 路径，以适配当前环境。
    # 修复：
    # 1. 优先使用 WEB_PLATFORM_URL 配置来构建绝对路径（包含正确的端口），
    #    以满足必须返回 https://domain:port/thumbs/... 的需求。
    # 2. 如果未配置，则回退为相对路径。

    rel_path = rel_path.replace(os.path.sep, "/")
    from urllib.parse import quote, urlparse
    encoded_path = quote(rel_path)

    relative_url = f"{mount_point}/{encoded_path}"

    if settings.WEB_PLATFORM_URL:
        try:
            parsed = urlparse(settings.WEB_PLATFORM_URL)
            # 提取 scheme://netloc (包含端口)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            return f"{base_url}{relative_url}"
        except Exception:
            # 解析失败则降级
            pass

    return relative_url
