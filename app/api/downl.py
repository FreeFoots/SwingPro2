import os
import shutil
import uuid
import zipfile
import re
import hashlib
from datetime import datetime, timedelta, time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, case

from app.core.deps import get_db, role_at_least, require_scope
from app.core.logging_config import get_logger
from app.core.security import BEIJING_TZ, now_bj
from app.core.config import settings
from app.db.models.user import User, RoleEnum, Player
from app.db.models.video import Video
from app.schemas.downl import (
    DayVideoSummary,
    DayVideoListResponse,
    DayVideoCountSummary,
    DayVideoCountResponse,
    DaysRequest,
    DayCountRequest,
    DownloadRequest,
    DownloadResponse,
    DownloadFavoriteResponse,
    DownloadVideoItem,
    DownloadFavoriteVideoItem,
    CopyVideosRequest,
    CopyVideosResponse,
)


router = APIRouter(prefix="/downl", tags=["downl"])
logger = get_logger(__name__)
ZIP_CACHE_TTL_SECONDS = 300  # 缓存 5 分钟，避免频繁重复打包


def _ensure_owner_access(actor: User, owner_id: str):
    """仅允许本人或管理角色访问"""
    if role_at_least(actor.role, RoleEnum.admin):
        return
    if actor.id == owner_id:
        return
    raise HTTPException(status_code=403, detail="无权访问该账号的视频")


def _normalize_unionid_filter(wechat_unionid: str | None) -> tuple[str, str | None]:
    if wechat_unionid == "-1":
        return "all", None
    # 按照指示：为空（空字符串或 None）或者是 'null' 字符串，都视为 guest (筛选 wechat_unionid 为空的视频)
    if not wechat_unionid or str(wechat_unionid).lower() == "null":
        return "guest", None
    return "user", wechat_unionid


def _get_owner_unionids(db: Session, owner_id: str) -> list[str]:
    rows = db.query(Player.wechat_unionid).filter(Player.owner_id == owner_id).all()
    return [row[0] for row in rows if row and row[0]]


def _apply_unionid_filter(query, mode: str, unionid_value: str | None, player_unionids: list[str]):
    unionid_col = Video.wechat_unionid
    if mode == "all":
        return query
    if mode == "guest":
        if not player_unionids:
            return query
        return query.filter(
            or_(
                unionid_col.is_(None),
                unionid_col == "",
                ~unionid_col.in_(player_unionids),
            )
        )
    if mode == "user":
        if unionid_value:
            return query.filter(unionid_col == unionid_value)
        if not player_unionids:
            return query.filter(False)
        return query.filter(unionid_col.in_(player_unionids))
    return query


def _bj_day_range(target_date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=BEIJING_TZ)
    end = start + timedelta(days=1)
    return start, end


def _normalize_videos_ids(video_ids: list[str] | None) -> set[str]:
    if not video_ids:
        return set()
    return {str(v).strip() for v in video_ids if str(v).strip()}


def _extract_local_videos_ids(payload, video_ids: list[str] | None) -> set[str]:
    names: list[str] = []
    if payload:
        if getattr(payload, "video_ids", None):
            names.extend(payload.video_ids)
        if getattr(payload, "videos_ids", None):
            names.extend(payload.videos_ids)
        data = getattr(payload, "data", None)
        if data:
            if getattr(data, "video_ids", None):
                names.extend(data.video_ids)
            if getattr(data, "videos_ids", None):
                names.extend(data.videos_ids)
    if video_ids:
        names.extend(video_ids)
    return _normalize_videos_ids(names)


def _debug_print_videos(label: str, videos: list[Video]) -> None:
    logger.debug("DEBUG: %s count=%s", label, len(videos))
    for v in videos:
        logger.debug(
            "DEBUG: %s item: id=%s name=%s owner_id=%s unionid=%s pair_session_id=%s is_primary=%s deleted=%s "
            "photo_at=%s created_at=%s file_path=%s",
            label,
            v.id,
            v.name,
            v.owner_id,
            v.wechat_unionid,
            v.pair_session_id,
            v.is_primary_video,
            v.deleted,
            v.photo_at,
            v.created_at,
            v.file_path,
        )


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


def _video_name_dedup_key(video: Video) -> str:
    name = str(video.name or "").strip().lower()
    if name:
        return name
    return f"__video_id__{video.id}"


def _is_paired_slave_video(video: Video) -> bool:
    sid = _normalize_pair_session_id(video.pair_session_id)
    return bool(sid) and _is_primary_video_false(video.is_primary_video)


def _filter_download_base_videos(videos: list[Video], local_names: set[str]) -> tuple[list[Video], int, int]:
    """
    /downl/download 基准筛选：
    - 仅对主视频/单独视频做“本地已存在”校验。
    - 当同组主视频在当前候选中存在时，从视频作为附庸剔除，后续由主视频命中后统一补入。
    - 当当前候选中不存在同组主视频时，从视频视为单独视频，不剔除。
    """
    filtered: list[Video] = []
    skipped_local_primary = 0
    skipped_paired_slave = 0

    # 仅基于“当前候选视频集合”判断某个从视频是否有可依附主视频。
    primary_sessions_in_scope: set[str] = set()
    for video in videos:
        sid = _pair_session_lookup_key(video.pair_session_id)
        if sid and _is_primary_video_true(video.is_primary_video):
            primary_sessions_in_scope.add(sid)

    for video in videos:
        sid = _pair_session_lookup_key(video.pair_session_id)
        if sid and _is_primary_video_false(video.is_primary_video) and sid in primary_sessions_in_scope:
            skipped_paired_slave += 1
            continue

        name = str(video.name or "").strip()
        if local_names and name and name in local_names:
            skipped_local_primary += 1
            continue

        filtered.append(video)

    return filtered, skipped_local_primary, skipped_paired_slave


def _dedup_videos_for_download(videos: list[Video]) -> list[Video]:
    """
    下载去重：同一物理视频仅保留一条记录。
    以 file_path 优先作为去重键，file_path 缺失时回退到 (name, thumb_path)。
    这样可避免数据库存在重复记录时，zip 内文件名被自动加 _1/_2。
    """
    deduped: list[Video] = []
    seen: set[tuple[str, str, str]] = set()
    for v in videos:
        key = (
            str(v.file_path or "").strip().lower(),
            str(v.name or "").strip().lower(),
            str(v.thumb_path or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(v)
    return deduped


def _expand_with_paired_slaves(db: Session, videos: list[Video]) -> list[Video]:
    primary_sessions: set[str] = set()
    for v in videos:
        sid = _pair_session_lookup_key(v.pair_session_id)
        if sid and _is_primary_video_true(v.is_primary_video):
            primary_sessions.add(sid)
    if not primary_sessions:
        return videos

    pair_expr = func.lower(func.btrim(Video.pair_session_id))
    paired_candidates = (
        db.query(Video)
        .filter(
            Video.deleted == False,  # noqa: E712
            Video.pair_session_id.isnot(None),
            pair_expr.in_(list(primary_sessions)),
        )
        .order_by(Video.created_at.asc(), Video.id.asc())
        .all()
    )
    slave_videos = [v for v in paired_candidates if _is_primary_video_false(v.is_primary_video)]
    if not slave_videos:
        return videos

    combined = videos + [v for v in slave_videos if _is_primary_video_false(v.is_primary_video)]
    before = len(combined)

    # 主从扩展后按视频名去重（同名仅保留第一条，优先保留主搜索结果中的记录）。
    deduped: list[Video] = []
    seen_names: set[str] = set()
    for v in combined:
        key = _video_name_dedup_key(v)
        if key in seen_names:
            continue
        seen_names.add(key)
        deduped.append(v)

    logger.debug(
        "DEBUG: /downl/download paired-slaves expansion - primary_sessions=%s add=%s before_name_dedup=%s after_name_dedup=%s",
        sorted(primary_sessions),
        len(slave_videos),
        before,
        len(deduped),
    )
    return deduped


def _expand_copy_sources_with_paired_slaves(db: Session, videos: list[Video]) -> tuple[list[Video], dict[str, str]]:
    """
    /downl/copy 的配对扩展：
    - 仅当请求中命中的视频里存在“主视频(有 pair_session_id 且 is_primary=true)”时，补入同 session 的从视频。
    - 复制时为该 session 生成新的 pair_session_id，避免复用原分组ID。
    """
    primary_sessions: set[str] = set()
    for v in videos:
        sid = _pair_session_lookup_key(v.pair_session_id)
        if sid and _is_primary_video_true(v.is_primary_video):
            primary_sessions.add(sid)

    if not primary_sessions:
        return videos, {}

    pair_expr = func.lower(func.btrim(Video.pair_session_id))
    paired_candidates = (
        db.query(Video)
        .filter(
            Video.deleted == False,  # noqa: E712
            Video.pair_session_id.isnot(None),
            pair_expr.in_(list(primary_sessions)),
        )
        .order_by(Video.created_at.asc(), Video.id.asc())
        .all()
    )
    slave_videos = [v for v in paired_candidates if _is_primary_video_false(v.is_primary_video)]

    combined = list(videos)
    seen_ids = {v.id for v in combined}
    added = 0
    for v in slave_videos:
        if v.id in seen_ids:
            continue
        combined.append(v)
        seen_ids.add(v.id)
        added += 1

    remapped_pair_sessions = {
        sid: str(uuid.uuid4()).upper()
        for sid in sorted(primary_sessions)
    }
    logger.debug(
        "DEBUG: /downl/copy paired-slaves expansion - primary_sessions=%s add=%s remap_groups=%s",
        sorted(primary_sessions),
        added,
        len(remapped_pair_sessions),
    )
    return combined, remapped_pair_sessions


def _find_cached_zips(safe_key: str, date_str: str) -> List[str]:
    prefix = f"{safe_key}_{date_str}_"
    # timestamp -> list of (path, mtime, filename)
    groups = {}
    try:
        if not os.path.exists(settings.VIDEO_TMP_ROOT):
            return []
        for name in os.listdir(settings.VIDEO_TMP_ROOT):
            if not name.startswith(prefix) or not name.endswith(".zip"):
                continue
            path = os.path.join(settings.VIDEO_TMP_ROOT, name)
            if not os.path.isfile(path):
                continue

            # Extract timestamp: prefix is "safe_key_date_"
            # Filename is either "prefix + timestamp.zip" or "prefix + timestamp_partN.zip"
            remainder = name[len(prefix):]
            parts = remainder.split("_")
            # The first part of remainder is the timestamp (e.g. 123456)
            ts_str = parts[0].replace(".zip", "")

            if ts_str not in groups:
                groups[ts_str] = []
            groups[ts_str].append((path, os.path.getmtime(path), name))

    except FileNotFoundError:
        return []

    if not groups:
        return []

    now_ts = now_bj().timestamp()
    valid_groups = []

    for ts_str, items in groups.items():
        # Get the latest modification time in this group
        grp_mtime = max(item[1] for item in items)
        if now_ts - grp_mtime <= ZIP_CACHE_TTL_SECONDS:
            # Check for zero byte files
            if all(os.path.getsize(item[0]) > 0 for item in items):
                valid_groups.append((grp_mtime, items))

    if not valid_groups:
        return []

    # Pick the most recent group
    _, best_items = max(valid_groups, key=lambda x: x[0])

    # Sort by part number naturally
    def sort_key(item):
        fname = item[2]
        m = re.search(r'_part(\d+)\.zip$', fname)
        if m:
            return int(m.group(1))
        return 0

    best_items.sort(key=sort_key)

    return [item[0] for item in best_items]


def _find_cached_draw_zip(safe_key: str, date_str: str) -> str | None:
    prefix = f"{safe_key}_{date_str}_draws_"
    try:
        if not os.path.exists(settings.VIDEO_TMP_ROOT):
            return None
        candidates: list[tuple[float, str]] = []
        for name in os.listdir(settings.VIDEO_TMP_ROOT):
            if not name.startswith(prefix) or not name.endswith(".zip"):
                continue
            path = os.path.join(settings.VIDEO_TMP_ROOT, name)
            if not os.path.isfile(path) or os.path.getsize(path) <= 0:
                continue
            mtime = os.path.getmtime(path)
            if now_bj().timestamp() - mtime <= ZIP_CACHE_TTL_SECONDS:
                candidates.append((mtime, path))
    except FileNotFoundError:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _local_list_key(local_names: set[str]) -> str:
    if not local_names:
        return "all"
    digest = hashlib.sha256("\n".join(sorted(local_names)).encode()).hexdigest()[:8]
    return f"local_{digest}"


def _build_copied_video_path(src_path: str) -> str:
    directory = os.path.dirname(src_path)
    base = os.path.basename(src_path)
    name, ext = os.path.splitext(base)
    prefix, sep, _ = name.rpartition("_")
    if not sep:
        prefix = name
    while True:
        new_uuid = str(uuid.uuid4()).upper()
        new_name = f"{prefix}_{new_uuid}{ext}"
        candidate = os.path.join(directory, new_name)
        if not os.path.exists(candidate):
            return candidate


def _copy_thumb_file(src_thumb: str | None, new_video_path: str) -> str | None:
    if not src_thumb or not os.path.exists(src_thumb):
        return None
    thumb_dir = os.path.dirname(src_thumb)
    new_base = os.path.splitext(os.path.basename(new_video_path))[0]
    new_thumb = os.path.join(thumb_dir, f"{new_base}_thumb.jpg")
    shutil.copy2(src_thumb, new_thumb)
    return new_thumb


@router.post("/days", response_model=DayVideoListResponse)
def list_days_by_owner(
    payload: DaysRequest,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    """
    按天统计某个 owner 下的视频数量（自然日，按北京时间）
    """
    owner_id = payload.owner_id
    wechat_unionid = payload.wechat_unionid
    # target_date = payload.day # DaysRequest 中并没有 day 字段，且后续逻辑无需 day
    logger.debug(
        "DEBUG: /downl/days request - owner_id: %s, wechat_unionid: %s, user: %s",
        owner_id,
        wechat_unionid,
        current_user.id,
    )
    # Print request payload
    logger.debug(f"DEBUG: /downl/days request payload: {payload.model_dump_json() if hasattr(payload, 'model_dump_json') else payload.json()}")

    if not owner_id:
        raise HTTPException(status_code=400, detail="请提供 owner_id")

    _ensure_owner_access(current_user, owner_id)

    mode, unionid_value = _normalize_unionid_filter(wechat_unionid)
    player_unionids = _get_owner_unionids(db, owner_id)

    date_expr = func.date(
        func.timezone("Asia/Shanghai", func.coalesce(Video.photo_at, Video.created_at))
    )
    query = (
        db.query(date_expr.label("day"), func.count(Video.id))
        .filter(
            Video.owner_id == owner_id,
            Video.deleted == False,  # noqa: E712
        )
    )
    query = _apply_unionid_filter(query, mode, unionid_value, player_unionids)
    rows: List[tuple] = (
        query.group_by(date_expr)
        .order_by(date_expr.desc())
        .all()
    )
    items = [DayVideoSummary(date=row[0], count=row[1]) for row in rows]
    result = DayVideoListResponse(owner_id=owner_id, wechat_unionid=wechat_unionid, items=items)

    logger.debug("DEBUG: /downl/days response - total items: %s", len(result.items))
    # 若需打印全部详情，可取消注释下行（可能数据量大）
    # print(f"DEBUG: /downl/days response detail: {result.json(ensure_ascii=False)}")
    logger.debug(f"DEBUG: /downl/days response: {result.model_dump_json() if hasattr(result, 'model_dump_json') else result.json(ensure_ascii=False)}")

    return result


@router.post("/daycount", response_model=DayVideoCountResponse)
def day_count(
    payload: DayCountRequest,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    owner_id = payload.owner_id
    wechat_unionid = payload.wechat_unionid
    target_date = payload.day
    local_names = _normalize_videos_ids(payload.videos_ids)

    logger.debug(
        "DEBUG: /downl/daycount request - owner_id: %s, wechat_unionid: %s, day: %s, user: %s",
        owner_id,
        wechat_unionid,
        target_date,
        current_user.id,
    )
    # Print request payload
    logger.debug(f"DEBUG: /downl/daycount request payload: {payload.model_dump_json() if hasattr(payload, 'model_dump_json') else payload.json()}")

    if not owner_id or not target_date:
        raise HTTPException(status_code=400, detail="缺少必要参数")

    _ensure_owner_access(current_user, owner_id)

    start, end = _bj_day_range(target_date)
    ts_column = func.coalesce(Video.photo_at, Video.created_at)
    mode, unionid_value = _normalize_unionid_filter(wechat_unionid)
    player_unionids = _get_owner_unionids(db, owner_id)

    base = (
        db.query(Video)
        .filter(
            Video.owner_id == owner_id,
            Video.deleted == False,  # noqa: E712
            ts_column >= start,
            ts_column < end,
        )
    )
    base = _apply_unionid_filter(base, mode, unionid_value, player_unionids)

    if local_names:
        exist_case = case((Video.name.in_(list(local_names)), 1), else_=0)
        total, exist_count = (
            base.with_entities(func.count(Video.id), func.coalesce(func.sum(exist_case), 0))
            .first()
            or (0, 0)
        )
    else:
        total = base.with_entities(func.count(Video.id)).scalar() or 0
        exist_count = 0

    count = max(int(total) - int(exist_count), 0)
    items = [DayVideoCountSummary(date=target_date, count=count, exist_count=int(exist_count))]

    resp = DayVideoCountResponse(
        owner_id=owner_id,
        wechat_unionid=wechat_unionid,
        items=items,
    )
    # Print response
    logger.debug(f"DEBUG: /downl/daycount response: {resp.model_dump_json() if hasattr(resp, 'model_dump_json') else resp.json(ensure_ascii=False)}")
    return resp



def _process_remaining_zips(tasks: List[dict]):
    """Background task to process remaining zip chunks"""
    for task in tasks:
        zip_path = task['zip_path']
        video_paths = task['video_paths']

        # 为了避免写一半被读取，可以先写临时文件
        tmp_zip_path = zip_path + ".tmp"
        try:
            with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
                 # Re-implement simplified _add_videos_to_zip logic here to avoid DB object dependency issues
                 _add_video_files_to_zip(archive, video_paths)

            # Atomic move
            if os.path.exists(tmp_zip_path):
                os.rename(tmp_zip_path, zip_path)
                logger.debug("DEBUG: Background zip created: %s", zip_path)
        except Exception as e:
            logger.error("ERROR: Background zip failed for %s: %s", zip_path, e)
            if os.path.exists(tmp_zip_path):
                os.remove(tmp_zip_path)

def _add_video_files_to_zip(archive: zipfile.ZipFile, video_paths: List[str]) -> int:
    count = 0
    existing_names: set[str] = set()
    for file_path in video_paths:
        if not file_path or not os.path.exists(file_path):
            continue
        base = os.path.basename(file_path)
        name, ext = os.path.splitext(base)
        candidate = base
        counter = 1
        while candidate in existing_names:
            candidate = f"{name}_{counter}{ext}"
            counter += 1
        archive.write(file_path, arcname=candidate)
        existing_names.add(candidate)
        count += 1
    return count


def _add_named_files_to_zip(archive: zipfile.ZipFile, entries: list[tuple[str, str]]) -> int:
    count = 0
    existing_names: set[str] = set()
    for file_path, target_name in entries:
        if not file_path or not os.path.exists(file_path):
            continue

        base_target = os.path.basename(target_name)
        name, ext = os.path.splitext(base_target)
        candidate = base_target
        counter = 1
        while candidate in existing_names:
            candidate = f"{name}_{counter}{ext}"
            counter += 1

        archive.write(file_path, arcname=candidate)
        existing_names.add(candidate)
        count += 1
    return count


def _collect_json_entries(videos: list[Video], path_field: str, filename_prefix: str = "") -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    for video in videos:
        path = str(getattr(video, path_field, "") or "").strip()
        if not path or path in seen_paths:
            continue
        if not os.path.isfile(path):
            continue
        seen_paths.add(path)

        source_name = str(video.file_path or video.name or f"video_{video.id}").strip()
        source_base = os.path.basename(source_name)
        source_stem, _ = os.path.splitext(source_base)
        if not source_stem:
            source_stem = f"video_{video.id}"
        draw_name = f"{filename_prefix}{source_stem}.json"
        entries.append((path, draw_name))
    return entries


def _collect_draw_entries(videos: list[Video]) -> list[tuple[str, str]]:
    return _collect_json_entries(videos, "drawed_path")


def _collect_multi_draw_entries(videos: list[Video]) -> list[tuple[str, str]]:
    primary_videos: list[Video] = []
    for video in videos:
        sid = _normalize_pair_session_id(video.pair_session_id)
        is_primary = _is_primary_video_true(video.is_primary_video) if sid else True
        if is_primary:
            primary_videos.append(video)
    return _collect_json_entries(primary_videos, "multi_drawed_path", "multi_")


def _prepare_draw_zip(videos: list[Video], safe_key: str, date_str: str) -> str | None:
    draw_entries = _collect_draw_entries(videos)
    if not draw_entries:
        return None

    cached = _find_cached_draw_zip(safe_key, date_str)
    if cached:
        try:
            os.utime(cached, None)
        except OSError:
            logger.warning("Failed to touch cached draw zip: %s", cached)
        return cached

    timestamp = now_bj().strftime("%H%M%S")
    draw_zip_name = f"{safe_key}_{date_str}_draws_{timestamp}.zip"
    draw_zip_path = os.path.join(settings.VIDEO_TMP_ROOT, draw_zip_name)
    tmp_zip_path = draw_zip_path + ".tmp"
    added = 0
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            added = _add_named_files_to_zip(archive, draw_entries)
        if added == 0:
            if os.path.exists(tmp_zip_path):
                os.remove(tmp_zip_path)
            return None
        if os.path.exists(tmp_zip_path):
            os.rename(tmp_zip_path, draw_zip_path)
        return draw_zip_path
    except Exception:
        if os.path.exists(tmp_zip_path):
            os.remove(tmp_zip_path)
        raise


def _prepare_multi_draw_zip(videos: list[Video], safe_key: str, date_str: str) -> str | None:
    draw_entries = _collect_multi_draw_entries(videos)
    if not draw_entries:
        return None

    safe_multi_key = f"{safe_key}_multi"
    cached = _find_cached_draw_zip(safe_multi_key, date_str)
    if cached:
        try:
            os.utime(cached, None)
        except OSError:
            logger.warning("Failed to touch cached multi draw zip: %s", cached)
        return cached

    timestamp = now_bj().strftime("%H%M%S")
    draw_zip_name = f"{safe_multi_key}_{date_str}_draws_{timestamp}.zip"
    draw_zip_path = os.path.join(settings.VIDEO_TMP_ROOT, draw_zip_name)
    tmp_zip_path = draw_zip_path + ".tmp"
    added = 0
    try:
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            added = _add_named_files_to_zip(archive, draw_entries)
        if added == 0:
            if os.path.exists(tmp_zip_path):
                os.remove(tmp_zip_path)
            return None
        if os.path.exists(tmp_zip_path):
            os.rename(tmp_zip_path, draw_zip_path)
        return draw_zip_path
    except Exception:
        if os.path.exists(tmp_zip_path):
            os.remove(tmp_zip_path)
        raise


def _safe_filename_token(value: str | None, limit: int = 32) -> str:
    text = str(value or "unknown")
    safe = "".join(ch if ch.isalnum() else "_" for ch in text)[:limit]
    return safe or "unknown"


def _selection_digest(videos: list[Video]) -> str:
    rows = [
        f"{v.id}:{v.name or ''}:{v.file_path or ''}:{v.isFavorited}"
        for v in videos
    ]
    digest = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()[:10]
    return f"sel_{digest}"


def _download_filter_tag(mode: str, unionid_value: str | None, local_names: set[str]) -> str:
    filter_tag = mode
    if mode == "user" and unionid_value:
        filter_tag = f"user_{_safe_filename_token(unionid_value, 16)}"
    local_key = _local_list_key(local_names)
    if local_key != "all":
        filter_tag = f"{filter_tag}_{local_key}"
    return filter_tag


def _get_base_url(req: Request) -> str:
    if settings.WEB_PLATFORM_URL:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(settings.WEB_PLATFORM_URL)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            pass
    return str(req.base_url).rstrip("/")


def _build_download_payload(
    video_urls: list[str],
    draw_urls: list[str],
    multi_draw_urls: list[str],
    source_videos: list[Video],
    include_primary_wechat_unionid: bool = False,
) -> DownloadResponse | DownloadFavoriteResponse:
    primary_by_session: dict[str, Video] = {}
    for video in source_videos:
        sid = _normalize_pair_session_id(video.pair_session_id)
        if not sid or not _is_primary_video_true(video.is_primary_video):
            continue
        current = primary_by_session.get(sid)
        if not current:
            primary_by_session[sid] = video
            continue
        if current.created_at is None or (video.created_at is not None and video.created_at > current.created_at):
            primary_by_session[sid] = video

    items: list[DownloadVideoItem | DownloadFavoriteVideoItem] = []
    for video in source_videos:
        sid = _normalize_pair_session_id(video.pair_session_id)
        is_primary = _is_primary_video_true(video.is_primary_video) if sid else True
        primary_video = primary_by_session.get(sid) if sid else None
        favorite_source = primary_video if (sid and not is_primary and primary_video) else video

        item_data = {
            "video_id": video.name or str(video.id),
            "is_favorited": bool(favorite_source.isFavorited),
            "pair_session_id": sid,
            "is_primary_video": is_primary,
        }
        if include_primary_wechat_unionid:
            if is_primary:
                item_data["wechat_unionid"] = video.wechat_unionid
            items.append(
                DownloadFavoriteVideoItem(
                    **item_data,
                )
            )
        else:
            items.append(
                DownloadVideoItem(
                    **item_data,
                )
            )

    response_model = DownloadFavoriteResponse if include_primary_wechat_unionid else DownloadResponse
    return response_model(
        video_urls=video_urls,
        draw_urls=draw_urls,
        multi_draw_urls=multi_draw_urls,
        total_videos=len(items),
        items=items,
    )


def _prepare_download_archives(
    request: Request,
    videos: list[Video],
    safe_key: str,
    date_str: str,
    background_tasks: BackgroundTasks,
    log_prefix: str,
    include_primary_wechat_unionid: bool = False,
) -> DownloadResponse | DownloadFavoriteResponse:
    os.makedirs(settings.VIDEO_TMP_ROOT, exist_ok=True)

    cached_paths = _find_cached_zips(safe_key, date_str)
    base_url = _get_base_url(request)

    draw_zip_path = _prepare_draw_zip(videos, safe_key, date_str)
    draw_urls: list[str] = []
    if draw_zip_path:
        draw_urls.append(f"{base_url}/download_temp/{os.path.basename(draw_zip_path)}")

    multi_draw_zip_path = _prepare_multi_draw_zip(videos, safe_key, date_str)
    multi_draw_urls: list[str] = []
    if multi_draw_zip_path:
        multi_draw_urls.append(f"{base_url}/download_temp/{os.path.basename(multi_draw_zip_path)}")

    if cached_paths:
        logger.debug(
            "DEBUG: %s response - returning cached files: %s files",
            log_prefix,
            len(cached_paths),
        )
        urls = []
        for path in cached_paths:
            fname = os.path.basename(path)
            urls.append(f"{base_url}/download_temp/{fname}")
            try:
                os.utime(path, None)
            except OSError:
                logger.warning("Failed to touch cached zip: %s", path)
        logger.debug("DEBUG: %s cached urls=%s", log_prefix, urls)
        return _build_download_payload(
            urls,
            draw_urls,
            multi_draw_urls,
            videos,
            include_primary_wechat_unionid=include_primary_wechat_unionid,
        )

    timestamp = now_bj().strftime("%H%M%S")
    zip_filename_base = f"{safe_key}_{date_str}_{timestamp}"

    max_videos_per_zip = 100
    total_videos = len(videos)

    if total_videos <= max_videos_per_zip:
        unique_zip_name = f"{zip_filename_base}.zip"
        zip_path = os.path.join(settings.VIDEO_TMP_ROOT, unique_zip_name)
        tmp_zip_path = zip_path + ".tmp"

        added = 0
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            added = _add_videos_to_zip(archive, videos)

        if added == 0:
            if os.path.exists(tmp_zip_path):
                os.remove(tmp_zip_path)
            logger.debug("DEBUG: %s response - 404 No valid video files to zip", log_prefix)
            raise HTTPException(status_code=404, detail="暂无可打包的视频文件")

        if os.path.exists(tmp_zip_path):
            os.rename(tmp_zip_path, zip_path)

        logger.debug("DEBUG: %s response - single zip URL: %s", log_prefix, zip_path)
        download_url = f"{base_url}/download_temp/{unique_zip_name}"
        logger.debug("DEBUG: %s url=%s", log_prefix, download_url)
        return _build_download_payload(
            [download_url],
            draw_urls,
            multi_draw_urls,
            videos,
            include_primary_wechat_unionid=include_primary_wechat_unionid,
        )

    logger.debug("DEBUG: Splitting %s videos into multiple packages", total_videos)
    chunks = [videos[i:i + max_videos_per_zip] for i in range(0, total_videos, max_videos_per_zip)]

    links = []
    bg_tasks_data = []

    for i, chunk in enumerate(chunks):
        part_num = i + 1
        unique_part_name = f"{zip_filename_base}_part{part_num:03d}.zip"
        sub_zip_path = os.path.join(settings.VIDEO_TMP_ROOT, unique_part_name)

        download_url = f"{base_url}/download_temp/{unique_part_name}"
        links.append(download_url)

        if i == 0:
            logger.debug("DEBUG: Synchronously processing part 1: %s", unique_part_name)
            tmp_zip_path = sub_zip_path + ".tmp"
            try:
                with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as sub_archive:
                    _add_videos_to_zip(sub_archive, chunk)
                if os.path.exists(tmp_zip_path):
                    os.rename(tmp_zip_path, sub_zip_path)
            except Exception as e:
                if os.path.exists(tmp_zip_path):
                    os.remove(tmp_zip_path)
                raise HTTPException(status_code=500, detail=f"打包失败: {e}")
        else:
            video_paths = [v.file_path for v in chunk if v.file_path]
            bg_tasks_data.append({
                "zip_path": sub_zip_path,
                "video_paths": video_paths,
            })

    if bg_tasks_data:
        logger.debug(
            "DEBUG: Queueing background tasks for %s remaining parts",
            len(bg_tasks_data),
        )
        background_tasks.add_task(_process_remaining_zips, bg_tasks_data)

    logger.debug("DEBUG: %s urls=%s", log_prefix, links)
    return _build_download_payload(
        links,
        draw_urls,
        multi_draw_urls,
        videos,
        include_primary_wechat_unionid=include_primary_wechat_unionid,
    )


@router.post(
    "/download",
    response_model=DownloadResponse,
)
def download_day_videos(
    request: Request,
    owner_id: str,
    date: str,
    background_tasks: BackgroundTasks,
    wechat_unionid: str | None = None,
    payload: DownloadRequest | None = Body(default=None),
    videos_ids: list[str] | None = Query(default=None),
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    """
    下载某个 owner 在指定自然日的视频（打包 zip）
    - date 传入格式：YYYY-MM-DD，北京时间
    """
    logger.debug(
        "DEBUG: /downl/download request - owner_id: %s, date: %s, wechat_unionid: %s, user: %s",
        owner_id,
        date,
        wechat_unionid,
        current_user.id,
    )

    if not owner_id or not date:
        raise HTTPException(status_code=400, detail="缺少必要参数")

    _ensure_owner_access(current_user, owner_id)

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式需为 YYYY-MM-DD")

    start, end = _bj_day_range(target_date)
    # 按照需求：优先 photo_at，无则回退到 created_at，避免出现“当天无视频”的误判
    ts_column = func.coalesce(Video.photo_at, Video.created_at)
    mode, unionid_value = _normalize_unionid_filter(wechat_unionid)
    player_unionids = _get_owner_unionids(db, owner_id)
    logger.debug(
        "DEBUG: /downl/download filters - mode=%s unionid_value=%s player_unionids=%s",
        mode,
        unionid_value,
        player_unionids,
    )
    local_names = _extract_local_videos_ids(payload, videos_ids)
    if local_names:
        logger.debug("DEBUG: /downl/download local_names=%s", sorted(local_names))

    query = (
        db.query(Video)
        .filter(
            Video.owner_id == owner_id,
            Video.deleted == False,  # noqa: E712
            ts_column >= start,
            ts_column < end,
        )
    )
    query = _apply_unionid_filter(query, mode, unionid_value, player_unionids)

    # 增加排序确保切分稳定
    query = query.order_by(ts_column.asc(), Video.id.asc())
    all_videos: List[Video] = query.all()
    videos, skipped_local_primary, skipped_paired_slave = _filter_download_base_videos(all_videos, local_names)
    logger.debug(
        "DEBUG: /downl/download base-filter raw=%s kept=%s skipped_local_primary=%s skipped_paired_slave=%s",
        len(all_videos),
        len(videos),
        skipped_local_primary,
        skipped_paired_slave,
    )

    before_dedup = len(videos)
    videos = _dedup_videos_for_download(videos)
    after_dedup = len(videos)
    videos = _expand_with_paired_slaves(db, videos)
    after_expand = len(videos)
    if after_dedup != before_dedup:
        logger.debug(
            "DEBUG: /downl/download dedup - before=%s after=%s removed=%s",
            before_dedup,
            after_dedup,
            before_dedup - after_dedup,
        )
    if after_expand != after_dedup:
        logger.debug(
            "DEBUG: /downl/download pair-expansion - before=%s after=%s added=%s",
            after_dedup,
            after_expand,
            after_expand - after_dedup,
        )
    _debug_print_videos("/downl/download matched", videos)

    if not videos:
        diag_query = (
            db.query(Video)
            .filter(
                Video.owner_id == owner_id,
                Video.deleted == False,  # noqa: E712
                func.coalesce(Video.photo_at, Video.created_at) >= start,
                func.coalesce(Video.photo_at, Video.created_at) < end,
            )
            .order_by(Video.created_at.asc(), Video.id.asc())
        )
        diag_videos = diag_query.all()
        _debug_print_videos("/downl/download diag_all", diag_videos)
        logger.debug("DEBUG: /downl/download response - 404 No videos found")
        raise HTTPException(status_code=404, detail="指定日期没有视频")

    safe_owner = _safe_filename_token(owner_id, 32)
    filter_tag = _download_filter_tag(mode, unionid_value, local_names)
    date_str = target_date.strftime("%Y%m%d")
    return _prepare_download_archives(
        request,
        videos,
        f"{safe_owner}_{filter_tag}",
        date_str,
        background_tasks,
        "/downl/download",
    )


@router.post(
    "/download_fav",
    response_model=DownloadFavoriteResponse,
    response_model_exclude_unset=True,
)
def download_favorite_videos(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    """
    下载当前登录用户收藏的全部视频（打包 zip）。
    """
    owner_id = current_user.id
    logger.debug(
        "DEBUG: /downl/download_fav request - owner_id: %s, user: %s",
        owner_id,
        current_user.id,
    )

    local_names: set[str] = set()

    ts_column = func.coalesce(Video.photo_at, Video.created_at)
    query = (
        db.query(Video)
        .filter(
            Video.owner_id == owner_id,
            Video.deleted == False,  # noqa: E712
            Video.isFavorited == True,  # noqa: E712
        )
    )
    query = query.order_by(ts_column.asc(), Video.id.asc())

    all_videos: List[Video] = query.all()
    videos, skipped_local_primary, skipped_paired_slave = _filter_download_base_videos(all_videos, local_names)
    logger.debug(
        "DEBUG: /downl/download_fav base-filter raw=%s kept=%s skipped_local_primary=%s skipped_paired_slave=%s",
        len(all_videos),
        len(videos),
        skipped_local_primary,
        skipped_paired_slave,
    )

    before_dedup = len(videos)
    videos = _dedup_videos_for_download(videos)
    after_dedup = len(videos)
    videos = _expand_with_paired_slaves(db, videos)
    after_expand = len(videos)
    if after_dedup != before_dedup:
        logger.debug(
            "DEBUG: /downl/download_fav dedup - before=%s after=%s removed=%s",
            before_dedup,
            after_dedup,
            before_dedup - after_dedup,
        )
    if after_expand != after_dedup:
        logger.debug(
            "DEBUG: /downl/download_fav pair-expansion - before=%s after=%s added=%s",
            after_dedup,
            after_expand,
            after_expand - after_dedup,
        )
    _debug_print_videos("/downl/download_fav matched", videos)

    if not videos:
        _debug_print_videos("/downl/download_fav diag_all", all_videos)
        logger.debug("DEBUG: /downl/download_fav response - 404 No favorite videos found")
        raise HTTPException(status_code=404, detail="暂无需要下载的收藏视频")

    safe_owner = _safe_filename_token(owner_id, 32)
    filter_tag = f"fav_{_local_list_key(local_names)}_{_selection_digest(videos)}"
    return _prepare_download_archives(
        request,
        videos,
        f"{safe_owner}_{filter_tag}",
        "favorites",
        background_tasks,
        "/downl/download_fav",
        include_primary_wechat_unionid=True,
    )


def _add_videos_to_zip(archive: zipfile.ZipFile, videos: List[Video]) -> int:
    """Helper to add video files to a zip archive with name collision handling."""
    count = 0
    existing_names: set[str] = set()
    for video in videos:
        file_path = video.file_path
        if not file_path or not os.path.exists(file_path):
            continue
        base = os.path.basename(file_path)
        name, ext = os.path.splitext(base)
        candidate = base
        counter = 1
        while candidate in existing_names:
            candidate = f"{name}_{counter}{ext}"
            counter += 1
        archive.write(file_path, arcname=candidate)
        existing_names.add(candidate)
        count += 1
    return count





@router.post("/copy", response_model=CopyVideosResponse)
def copy_videos(
    payload: CopyVideosRequest,
    current_user: User = Depends(require_scope("video", 2)),
    db: Session = Depends(get_db),
):
    logger.debug("DEBUG: /downl/copy request - payload: %s, user: %s", payload, current_user.id)

    if not payload.videos_ids:
        raise HTTPException(status_code=400, detail="请提供要复制的视频名称")

    # 去重并保序，避免请求参数本身重复
    video_names = list(dict.fromkeys(name.strip() for name in payload.videos_ids if name and str(name).strip()))
    if not video_names:
        raise HTTPException(status_code=400, detail="请提供要复制的视频名称")

    videos = (
        db.query(Video)
        .filter(Video.name.in_(video_names), Video.deleted == False)  # noqa: E712
        .all()
    )
    if not videos:
        raise HTTPException(status_code=404, detail="未找到可复制的视频")

    found_names = {video.name for video in videos if video.name}
    missing = [name for name in video_names if name not in found_names]
    if missing:
        raise HTTPException(status_code=404, detail=f"视频不存在: {', '.join(missing)}")

    requested_video_names = set(video_names)
    requested_source_ids = {v.id for v in videos}
    source_videos, remapped_pair_sessions = _expand_copy_sources_with_paired_slaves(db, videos)

    requested_success_names: set[str] = set()
    paired_slave_success_count = 0
    paired_slave_skipped_count = 0
    synced_drawed_count = 0
    processed_keys: set[tuple[str, str, str, str, str]] = set()

    for video in source_videos:
        source_sid_key = _pair_session_lookup_key(video.pair_session_id)
        target_pair_session_id = remapped_pair_sessions.get(source_sid_key, video.pair_session_id)
        is_requested_source = video.id in requested_source_ids
        source_name = str(video.name or "")

        # 重复校验：同一逻辑视频（name+file_path+unionid）只处理一次
        dedup_key = (
            str(video.name or ""),
            str(video.file_path or ""),
            str(video.wechat_unionid or ""),
            str(target_pair_session_id or ""),
            str(_is_primary_video_true(video.is_primary_video)),
        )
        if dedup_key in processed_keys:
            logger.debug("DEBUG: 跳过重复视频记录 %s - dedup_key=%s", video.id, dedup_key)
            continue
        processed_keys.add(dedup_key)

        # 1. 检查是否存在 unionid
        unionid = video.wechat_unionid
        if not unionid or str(unionid).lower() == "null" or str(unionid) == "-1":
            logger.debug("DEBUG: 跳过视频 %s - unionid为空或无效: %s", video.name, unionid)
            if not is_requested_source:
                paired_slave_skipped_count += 1
            continue

        # 2. 检查 unionid 是否能找到对应的 app_user
        target_user = (
            db.query(User)
            .filter(User.wechat_unionid == unionid)
            .first()
        )
        if not target_user:
            logger.debug("DEBUG: 跳过视频 %s - 未找到unionid=%s对应的app_user", video.name, unionid)
            if not is_requested_source:
                paired_slave_skipped_count += 1
            continue

        # 3. 检查该视频（同 file_path）是否已存在归属目标用户的记录
        # 只要同一视频任一记录已归属目标用户，即视为已copy过
        same_owner = (
            db.query(Video)
            .filter(
                Video.owner_id == target_user.id,
                Video.file_path == video.file_path,
                Video.deleted == False,  # noqa: E712
            )
            .first()
        )
        if same_owner:
            if video.drawed_path and same_owner.drawed_path != video.drawed_path:
                same_owner.drawed_path = video.drawed_path
                db.add(same_owner)
                synced_drawed_count += 1
            if video.multi_drawed_path and same_owner.multi_drawed_path != video.multi_drawed_path:
                same_owner.multi_drawed_path = video.multi_drawed_path
                db.add(same_owner)
            logger.debug("DEBUG: 跳过视频 %s - 目标用户已拥有该视频", video.name)
            if not is_requested_source:
                paired_slave_skipped_count += 1
            continue

        # 若目标用户已有该视频但被逻辑删除，则恢复该记录
        deleted_owner = (
            db.query(Video)
            .filter(
                Video.owner_id == target_user.id,
                Video.file_path == video.file_path,
                Video.deleted == True,  # noqa: E712
            )
            .order_by(Video.created_at.desc())
            .first()
        )
        if deleted_owner:
            deleted_owner.deleted = False
            deleted_owner.deleted_at = None
            deleted_owner.created_at = now_bj()
            if video.drawed_path:
                deleted_owner.drawed_path = video.drawed_path
            if video.multi_drawed_path:
                deleted_owner.multi_drawed_path = video.multi_drawed_path
            deleted_owner.pair_session_id = target_pair_session_id
            deleted_owner.is_primary_video = _is_primary_video_true(video.is_primary_video)
            db.add(deleted_owner)
            db.commit()
            logger.debug("DEBUG: 恢复视频 %s - 目标用户已存在被删除记录", video.name)
            if is_requested_source:
                if source_name in requested_video_names:
                    requested_success_names.add(source_name)
            else:
                paired_slave_success_count += 1
            continue

        if not video.file_path or not os.path.exists(video.file_path):
            # 文件不存在仍然报错，或者也可以选择跳过？
            # 保持原逻辑报错，或者改为跳过并打印日志
            raise HTTPException(status_code=404, detail=f"视频文件在云端不存在: {video.name or video.id}")

        new_video = Video(
            # 不复制文件，沿用原视频记录，仅修改 owner_id 与 created_at
            uploader_id=video.uploader_id,
            owner_id=target_user.id,  # ownerid填入从app_user表中找到的unionid对应的owner
            wechat_unionid=unionid,   # copy出来的视频对应的unionid就是上传时的unionid
            file_path=video.file_path,
            name=video.name,
            thumb_path=video.thumb_path,
            mime_type=video.mime_type,
            title=video.title,
            fps=video.fps,
            size_bytes=video.size_bytes,
            duration=video.duration,
            resolution=video.resolution,
            status=video.status,
            created_at=now_bj(),
            photo_at=video.photo_at,
            view_type=video.view_type,
            deleted=False,
            deleted_at=None,
            isFavorited=False,
            frames_path=video.frames_path,
            drawed_path=video.drawed_path,
            multi_drawed_path=video.multi_drawed_path,
            pair_session_id=target_pair_session_id,
            is_primary_video=_is_primary_video_true(video.is_primary_video),
        )
        db.add(new_video)
        if is_requested_source:
            if source_name in requested_video_names:
                requested_success_names.add(source_name)
        else:
            paired_slave_success_count += 1

    db.commit()
    requested_total = len(video_names)
    success_count = len(requested_success_names)
    skipped_count = max(requested_total - success_count, 0)
    paired_slave_total = paired_slave_success_count + paired_slave_skipped_count
    paired_slave_has_success = paired_slave_success_count > 0

    message = f"成功同步{success_count}个视频，{skipped_count}个视频无账户或已存在不可上传，同步画线路径{synced_drawed_count}个"

    response = CopyVideosResponse(
        message=message,
        success_count=success_count,
        skipped_count=skipped_count,
        requested_total=requested_total,
        paired_slave_total=paired_slave_total,
        paired_slave_success_count=paired_slave_success_count,
        paired_slave_skipped_count=paired_slave_skipped_count,
        paired_slave_has_success=paired_slave_has_success,
    )

    logger.debug("DEBUG: /downl/copy response - %s", response)
    return response
