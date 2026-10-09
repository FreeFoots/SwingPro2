"""
管理后台统计 API

提供给超级管理员使用的统计和监控接口
"""

import os
import glob
from datetime import timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, Integer, text

from app.core.deps import get_db, require_scope
from app.core.security import now_bj
from app.core.config import settings
from app.db.models.user import User, RoleEnum
from app.db.models.video import Video
from app.db.models.activity import ActivityLog, ActivityCategory, ActivityAction
from app.services.activity import (
    get_activity_summary,
    get_daily_stats,
    get_recent_activities,
    get_sensitive_activities,
)


router = APIRouter()


# ============== 系统监控 ==============

@router.get("/system/overview")
def get_system_overview(
    days: int = Query(7, ge=7, le=30, description="统计周期，支持 7/15/30 天"),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("overview", 1)),
):
    """
    系统概览

    包含：用户数、视频数等
    """
    now = now_bj()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_days = days if days in (7, 15, 30) else 7
    period_start = today_start - timedelta(days=window_days - 1)

    # 用户统计
    user_stats = db.query(
        func.count(User.id).label("total"),
        func.sum(func.cast(User.status == True, Integer)).label("active"),
    ).first()

    # 按角色统计用户
    role_stats = db.query(
        User.role,
        func.count(User.id).label("count"),
    ).group_by(User.role).all()

    # 视频统计
    video_stats = db.query(
        func.count(Video.id).label("total"),
        func.sum(Video.size_bytes).label("total_bytes"),
    ).filter(Video.deleted == False).first()

    # 今日统计
    today_new_users = db.query(func.count(User.id)).filter(
        User.created_at >= today_start,
    ).scalar()

    today_videos = db.query(func.count(Video.id)).filter(
        Video.created_at >= today_start,
        Video.deleted == False,
    ).scalar()

    today_logins = db.query(func.count(ActivityLog.id)).filter(
        ActivityLog.created_at >= today_start,
        ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
        func.json_extract_path_text(ActivityLog.detail, "client_type") == "app",
        ActivityLog.success == 1,
    ).scalar()

    today_online_users = db.query(func.count(func.distinct(ActivityLog.user_id))).filter(
        ActivityLog.created_at >= today_start,
        ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
        func.json_extract_path_text(ActivityLog.detail, "client_type") == "app",
        ActivityLog.success == 1,
        ActivityLog.user_id.isnot(None),
    ).scalar()

    # 近N天上传趋势（按 videos 统计：上传量 + 活跃上传用户数）
    trend_rows = (
        db.query(
            func.date(Video.created_at).label("day"),
            func.count(Video.id).label("upload_count"),
            func.count(func.distinct(Video.owner_id)).label("upload_users"),
        )
        .filter(
            Video.created_at >= period_start,
            Video.deleted == False,
        )
        .group_by(func.date(Video.created_at))
        .all()
    )
    trend_map = {
        str(row.day): {
            "upload_count": int(row.upload_count or 0),
            "upload_users": int(row.upload_users or 0),
        }
        for row in trend_rows
    }
    trend_items = []
    for i in range(window_days - 1, -1, -1):
        d = (today_start - timedelta(days=i)).date().isoformat()
        stat = trend_map.get(d, {"upload_count": 0, "upload_users": 0})
        trend_items.append(
            {
                "date": d,
                "count": stat["upload_count"],  # backward compatibility
                "upload_count": stat["upload_count"],
                "upload_users": stat["upload_users"],
            }
        )

    def _mask_tel(tel: str | None) -> str | None:
        if not tel:
            return None
        if len(tel) < 7:
            return tel
        return f"{tel[:3]}****{tel[-4:]}"

    # 用户画像分层（按近15天日均上传）+ 沉默用户（15天无登录或无上传）
    portrait_window_days = 15
    silent_window_days = 15
    portrait_start = today_start - timedelta(days=portrait_window_days - 1)
    silent_threshold = now - timedelta(days=silent_window_days)

    upload_owner_rows_portrait = (
        db.query(
            Video.owner_id,
            func.count(Video.id).label("upload_count"),
        )
        .filter(
            Video.created_at >= portrait_start,
            Video.deleted == False,
            Video.owner_id.isnot(None),
        )
        .group_by(Video.owner_id)
        .all()
    )
    upload_count_map = {row.owner_id: int(row.upload_count or 0) for row in upload_owner_rows_portrait}

    app_login_recent_user_ids = {
        row.user_id
        for row in (
            db.query(ActivityLog.user_id)
            .filter(
                ActivityLog.created_at >= silent_threshold,
                ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
                func.json_extract_path_text(ActivityLog.detail, "client_type") == "app",
                ActivityLog.success == 1,
                ActivityLog.user_id.isnot(None),
            )
            .group_by(ActivityLog.user_id)
            .all()
        )
    }

    app_login_last_rows = (
        db.query(
            ActivityLog.user_id,
            func.max(ActivityLog.created_at).label("last_login_at"),
        )
        .filter(
            ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
            func.json_extract_path_text(ActivityLog.detail, "client_type") == "app",
            ActivityLog.success == 1,
            ActivityLog.user_id.isnot(None),
        )
        .group_by(ActivityLog.user_id)
        .all()
    )
    app_last_login_map = {row.user_id: row.last_login_at for row in app_login_last_rows}

    recent_upload_owner_ids = {
        row.owner_id
        for row in (
            db.query(Video.owner_id)
            .filter(
                Video.created_at >= silent_threshold,
                Video.deleted == False,
                Video.owner_id.isnot(None),
            )
            .group_by(Video.owner_id)
            .all()
        )
    }

    last_upload_rows = (
        db.query(
            Video.owner_id,
            func.max(Video.created_at).label("last_upload_at"),
        )
        .filter(
            Video.deleted == False,
            Video.owner_id.isnot(None),
        )
        .group_by(Video.owner_id)
        .all()
    )
    last_upload_map = {row.owner_id: row.last_upload_at for row in last_upload_rows}

    users_for_layers = (
        db.query(User)
        .filter(User.role != RoleEnum.system_admin)
        .all()
    )
    total_users_for_layers = len(users_for_layers)

    layer_counts = {
        "high": 0,
        "medium": 0,
        "light": 0,
        "silent": 0,
    }

    silent_users = []
    high_users = []
    medium_users = []
    light_users = []
    for u in users_for_layers:
        upload_cnt = upload_count_map.get(u.id, 0)
        avg_daily_upload = upload_cnt / portrait_window_days
        last_login = app_last_login_map.get(u.id)
        last_upload_at = last_upload_map.get(u.id)
        has_recent_login = u.id in app_login_recent_user_ids
        has_recent_upload = u.id in recent_upload_owner_ids

        # 仅当"近N天无登录且无上传"时才归为沉默用户，避免有上传行为却被沉默覆盖。
        if (not has_recent_login) and (not has_recent_upload):
            layer_counts["silent"] += 1
            last_activity = max(
                [dt for dt in [last_login, last_upload_at] if dt is not None],
                default=None,
            )
            days_silent = None
            if last_activity:
                days_silent = max((now.date() - last_activity.date()).days, 0)
            silent_users.append(
                {
                    "user_id": u.id,
                    "username": u.username or _mask_tel(u.telephone) or "未知用户",
                    "telephone": _mask_tel(u.telephone),
                    "avatar_url": u.avatar_url,
                    "role": u.role.value if u.role else "unknown",
                    "last_login_at": last_login.isoformat() if last_login else None,
                    "last_upload_at": last_upload_at.isoformat() if last_upload_at else None,
                    "days_silent": days_silent,
                }
            )
            continue

        if avg_daily_upload >= 10:
            layer_counts["high"] += 1
            high_users.append(
                {
                    "user_id": u.id,
                    "username": u.username or _mask_tel(u.telephone) or "未知用户",
                    "telephone": _mask_tel(u.telephone),
                    "avatar_url": u.avatar_url,
                    "upload_count_window": upload_cnt,
                    "avg_daily_upload": round(avg_daily_upload, 2),
                }
            )
        elif avg_daily_upload >= 2:
            layer_counts["medium"] += 1
            medium_users.append(
                {
                    "user_id": u.id,
                    "username": u.username or _mask_tel(u.telephone) or "未知用户",
                    "telephone": _mask_tel(u.telephone),
                    "avatar_url": u.avatar_url,
                    "upload_count_window": upload_cnt,
                    "avg_daily_upload": round(avg_daily_upload, 2),
                }
            )
        else:
            layer_counts["light"] += 1
            light_users.append(
                {
                    "user_id": u.id,
                    "username": u.username or _mask_tel(u.telephone) or "未知用户",
                    "telephone": _mask_tel(u.telephone),
                    "avatar_url": u.avatar_url,
                    "upload_count_window": upload_cnt,
                    "avg_daily_upload": round(avg_daily_upload, 2),
                }
            )

    def _layer_ratio(count: int) -> float:
        if not total_users_for_layers:
            return 0.0
        return round((count / total_users_for_layers) * 100, 2)

    silent_users.sort(
        key=lambda item: item["days_silent"] if item["days_silent"] is not None else 9999,
        reverse=True,
    )

    high_users.sort(key=lambda item: item["upload_count_window"], reverse=True)
    medium_users.sort(key=lambda item: item["upload_count_window"], reverse=True)
    light_users.sort(key=lambda item: item["upload_count_window"], reverse=True)

    activity_layers = [
        {"key": "high", "label": "高活跃用户", "count": layer_counts["high"], "ratio": _layer_ratio(layer_counts["high"]), "rule": "15天日均>=10条"},
        {"key": "medium", "label": "中活跃用户", "count": layer_counts["medium"], "ratio": _layer_ratio(layer_counts["medium"]), "rule": "15天日均2-10条"},
        {"key": "light", "label": "低活跃用户", "count": layer_counts["light"], "ratio": _layer_ratio(layer_counts["light"]), "rule": "15天日均0-2条"},
        {"key": "silent", "label": "沉默用户", "count": layer_counts["silent"], "ratio": _layer_ratio(layer_counts["silent"]), "rule": "15天无登录且无上传（仅画像标记，不代表禁用）"},
    ]

    today_top_row = (
        db.query(
            Video.owner_id.label("user_id"),
            func.count(Video.id).label("upload_count"),
            User.username,
            User.telephone,
            User.avatar_url,
        )
        .outerjoin(User, User.id == Video.owner_id)
        .filter(
            Video.created_at >= today_start,
            Video.deleted == False,
            Video.owner_id.isnot(None),
        )
        .group_by(Video.owner_id, User.username, User.telephone, User.avatar_url)
        .order_by(func.count(Video.id).desc())
        .first()
    )
    today_top_uploader = None
    if today_top_row:
        today_top_uploader = {
            "user_id": today_top_row.user_id,
            "username": today_top_row.username or _mask_tel(today_top_row.telephone) or "未知用户",
            "telephone": _mask_tel(today_top_row.telephone),
            "avatar_url": today_top_row.avatar_url,
            "upload_count": int(today_top_row.upload_count or 0),
        }

    # 用户上传表（按视频类型分层展示）
    top_upload_rows = (
        db.query(
            Video.owner_id.label("user_id"),
            func.count(Video.id).label("upload_count"),
        )
        .filter(
            Video.created_at >= period_start,
            Video.deleted == False,
            Video.owner_id.isnot(None),
        )
        .group_by(Video.owner_id)
        .order_by(func.count(Video.id).desc())
        .limit(12)
        .all()
    )

    top_upload_user_ids = [row.user_id for row in top_upload_rows if row.user_id]
    top_upload_user_map: dict[str, User] = {}
    if top_upload_user_ids:
        top_upload_user_map = {
            u.id: u for u in db.query(User).filter(User.id.in_(top_upload_user_ids)).all()
        }

    user_upload_rows = []
    if top_upload_user_ids:
        videos_by_owner = (
            db.query(Video)
            .filter(
                Video.created_at >= period_start,
                Video.deleted == False,
                Video.owner_id.in_(top_upload_user_ids),
            )
            .order_by(Video.created_at.desc())
            .all()
        )

        per_owner = {
            uid: {
                "front": 0,
                "side": 0,
                "top": 0,
                "pro": 0,
                "other": 0,
            }
            for uid in top_upload_user_ids
        }

        for video in videos_by_owner:
            owner_id = video.owner_id
            if owner_id not in per_owner:
                continue
            item = per_owner[owner_id]
            if video.view_type == 1:
                item["front"] += 1
            elif video.view_type == 0:
                item["side"] += 1
            elif video.view_type == 3:
                item["top"] += 1
            elif video.view_type == 2:
                item["pro"] += 1
            else:
                item["other"] += 1

        for idx, row in enumerate(top_upload_rows, start=1):
            owner_id = row.user_id
            detail = per_owner.get(owner_id, {})
            user_obj = top_upload_user_map.get(owner_id)
            user_upload_rows.append(
                {
                    "rank": idx,
                    "user_id": owner_id,
                    "username": user_obj.username if user_obj and user_obj.username else _mask_tel(user_obj.telephone) if user_obj else "未知用户",
                    "telephone": _mask_tel(user_obj.telephone) if user_obj else None,
                    "avatar_url": user_obj.avatar_url if user_obj else None,
                    "role": user_obj.role.value if user_obj and user_obj.role else "unknown",
                    "upload_total": int(row.upload_count or 0),
                    "front_count": int(detail.get("front", 0)),
                    "side_count": int(detail.get("side", 0)),
                    "top_count": int(detail.get("top", 0)),
                    "pro_count": int(detail.get("pro", 0)),
                    "other_count": int(detail.get("other", 0)),
                }
            )

    # 用户行为统计（近7天）
    login_7d = db.query(func.count(ActivityLog.id)).filter(
        ActivityLog.created_at >= period_start,
        ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
        func.json_extract_path_text(ActivityLog.detail, "client_type") == "app",
        ActivityLog.success == 1,
    ).scalar()

    upload_7d = db.query(func.count(ActivityLog.id)).filter(
        ActivityLog.created_at >= period_start,
        ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
        ActivityLog.success == 1,
    ).scalar()

    upload_users_7d = db.query(func.count(func.distinct(ActivityLog.user_id))).filter(
        ActivityLog.created_at >= period_start,
        ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
        ActivityLog.success == 1,
        ActivityLog.user_id.isnot(None),
    ).scalar()

    # 用户管理行为（近7天）
    user_manage_actions = [
        ActivityAction.ROLE_CHANGE,
        ActivityAction.USER_DISABLE,
        ActivityAction.USER_ENABLE,
        ActivityAction.PASSWORD_CHANGE,
        ActivityAction.PASSWORD_RESET,
    ]
    management_rows = (
        db.query(
            ActivityLog.action,
            func.count(ActivityLog.id).label("count"),
        )
        .filter(
            ActivityLog.created_at >= period_start,
            ActivityLog.action.in_(user_manage_actions),
        )
        .group_by(ActivityLog.action)
        .all()
    )

    recent_manage_logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.created_at >= period_start,
            ActivityLog.action.in_(user_manage_actions),
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(20)
        .all()
    )

    # 视频上传统计（近7天 + 今日）
    upload_all_7d = (
        db.query(
            func.count(ActivityLog.id).label("total"),
            func.sum(ActivityLog.success).label("success"),
        )
        .filter(
            ActivityLog.created_at >= period_start,
            ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
        )
        .first()
    )
    upload_today = (
        db.query(
            func.count(ActivityLog.id).label("total"),
            func.sum(ActivityLog.success).label("success"),
        )
        .filter(
            ActivityLog.created_at >= today_start,
            ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
        )
        .first()
    )

    def _pct(numerator: int, denominator: int) -> float:
        if not denominator:
            return 0.0
        return round((numerator / denominator) * 100, 2)

    # 上传质量（近N天）
    video_quality = (
        db.query(
            func.count(Video.id).label("total"),
            func.avg(Video.duration).label("avg_duration"),
            func.avg(Video.size_bytes).label("avg_size_bytes"),
            func.sum(func.cast(Video.status.in_(["ready", "finished"]), Integer)).label("available"),
            func.sum(func.cast(Video.status == "failed", Integer)).label("failed"),
        )
        .filter(
            Video.created_at >= period_start,
            Video.deleted == False,
        )
        .first()
    )

    upload_fail_reasons = (
        db.query(
            ActivityLog.error_msg,
            func.count(ActivityLog.id).label("count"),
        )
        .filter(
            ActivityLog.created_at >= period_start,
            ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
            ActivityLog.success == 0,
            ActivityLog.error_msg.isnot(None),
            ActivityLog.error_msg != "",
        )
        .group_by(ActivityLog.error_msg)
        .order_by(func.count(ActivityLog.id).desc())
        .limit(5)
        .all()
    )

    role_profile = []
    total_users = int(user_stats.total or 0)
    for row in role_stats:
        role_name = row.role.value if row.role else "unknown"
        count = int(row.count or 0)
        ratio = round((count / total_users) * 100, 2) if total_users else 0
        role_profile.append({"role": role_name, "count": count, "ratio": ratio})

    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "users": {
            "total": total_users,
            "active": user_stats.active or 0,
            "by_role": {row.role.value if row.role else "unknown": row.count for row in role_stats},
            "profile": role_profile,
            "activity_layers": {
                "window_days": portrait_window_days,
                "items": activity_layers,
                "high_users": high_users,
                "medium_users": medium_users,
                "light_users": light_users,
                "silent_users": silent_users,
            },
            "silent_users": {
                "window_days": silent_window_days,
                "items": silent_users,
            },
        },
        "videos": {
            "total": video_stats.total or 0,
            "total_size_gb": round((video_stats.total_bytes or 0) / (1024**3), 2),
        },
        "today": {
            "new_users": today_new_users or 0,
            "new_videos": today_videos or 0,
            "logins": today_logins or 0,
            "online_users": today_online_users or 0,
            "top_uploader": today_top_uploader,
        },
        "user_details": {
            "behavior": {
                "logins_7d": login_7d or 0,
                "uploads_7d": upload_7d or 0,
                "upload_users_7d": upload_users_7d or 0,
            },
            "management": {
                "summary": [
                    {"action": row.action, "count": int(row.count or 0)}
                    for row in management_rows
                ],
                "recent": [
                    {
                        "time": log.created_at.isoformat() if log.created_at else None,
                        "action": log.action,
                        "user_telephone": log.user_telephone,
                        "user_role": log.user_role,
                        "target_type": log.target_type,
                        "target_id": log.target_id,
                        "success": log.success == 1,
                        "error": log.error_msg,
                    }
                    for log in recent_manage_logs
                ],
            },
        },
        "video_details": {
            "upload": {
                "total_7d": int(upload_all_7d.total or 0),
                "success_7d": int(upload_all_7d.success or 0),
                "failed_7d": int((upload_all_7d.total or 0) - (upload_all_7d.success or 0)),
                "total_today": int(upload_today.total or 0),
                "success_today": int(upload_today.success or 0),
                "failed_today": int((upload_today.total or 0) - (upload_today.success or 0)),
                "upload_users_7d": int(upload_users_7d or 0),
                "avg_daily_7d": round((int(upload_all_7d.total or 0) / window_days), 1),
                "total_window": int(upload_all_7d.total or 0),
                "upload_users_window": int(upload_users_7d or 0),
                "avg_daily_window": round((int(upload_all_7d.total or 0) / window_days), 1),
                "success_rate_window": _pct(int(upload_all_7d.success or 0), int(upload_all_7d.total or 0)),
            },
            "quality": {
                "avg_duration_sec": round(float(video_quality.avg_duration or 0), 1),
                "avg_size_mb": round(float(video_quality.avg_size_bytes or 0) / (1024 ** 2), 2),
                "total_window": int(video_quality.total or 0),
                "available_window": int(video_quality.available or 0),
                "failed_window": int(video_quality.failed or 0),
                "availability_rate": _pct(int(video_quality.available or 0), int(video_quality.total or 0)),
                "fail_reasons_top": [
                    {"reason": row.error_msg, "count": int(row.count or 0)}
                    for row in upload_fail_reasons
                ],
            },
            "user_upload_rows": user_upload_rows,
            "trend_7d": trend_items,
            "trend": trend_items,
        },
    }


@router.get("/system/checks")
def get_system_checks(
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    系统检查

    检查数据库、日志目录和近24小时核心失败指标。
    """
    now = now_bj()
    day_start = now - timedelta(hours=24)

    checks: list[dict] = []

    # DB连通性
    db_ok = True
    db_error = None
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)
    checks.append(
        {
            "key": "database",
            "name": "数据库连通性",
            "status": "ok" if db_ok else "error",
            "value": "正常" if db_ok else "异常",
            "detail": db_error,
        }
    )

    # 日志目录检查
    log_dir_abs = os.path.abspath(settings.LOG_DIR)
    log_dir_exists = os.path.isdir(log_dir_abs)
    error_logs = sorted(
        glob.glob(os.path.join(log_dir_abs, f"{settings.APP_NAME}.error.log*")),
        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
        reverse=True,
    )
    latest_error_log = error_logs[0] if error_logs else None
    latest_error_mtime = None
    if latest_error_log and os.path.exists(latest_error_log):
        latest_error_mtime = now_bj().fromtimestamp(os.path.getmtime(latest_error_log)).isoformat()

    checks.append(
        {
            "key": "log_dir",
            "name": "日志目录",
            "status": "ok" if log_dir_exists else "error",
            "value": log_dir_abs,
            "detail": f"error日志文件数: {len(error_logs)}",
            "latest_error_log_time": latest_error_mtime,
        }
    )

    # 近24小时失败率检查
    login_stats = (
        db.query(
            func.count(ActivityLog.id).label("total"),
            func.sum(func.cast(ActivityLog.success == 0, Integer)).label("failed"),
        )
        .filter(
            ActivityLog.created_at >= day_start,
            ActivityLog.action.in_([ActivityAction.LOGIN, ActivityAction.LOGIN_WECHAT]),
            func.coalesce(func.json_extract_path_text(ActivityLog.detail, "method"), "") != "refresh",
        )
        .first()
    )
    login_total = int(login_stats.total or 0)
    login_failed = int(login_stats.failed or 0)
    login_fail_rate = round((login_failed / login_total) * 100, 2) if login_total else 0
    checks.append(
        {
            "key": "login_fail_rate",
            "name": "登录失败率(24h)",
            "status": "warn" if login_fail_rate >= 5 else "ok",
            "value": f"{login_fail_rate}%",
            "detail": f"失败 {login_failed} / 总计 {login_total}",
        }
    )

    upload_stats = (
        db.query(
            func.count(ActivityLog.id).label("total"),
            func.sum(func.cast(ActivityLog.success == 0, Integer)).label("failed"),
        )
        .filter(
            ActivityLog.created_at >= day_start,
            ActivityLog.action == ActivityAction.VIDEO_UPLOAD,
        )
        .first()
    )
    upload_total = int(upload_stats.total or 0)
    upload_failed = int(upload_stats.failed or 0)
    upload_fail_rate = round((upload_failed / upload_total) * 100, 2) if upload_total else 0
    checks.append(
        {
            "key": "upload_fail_rate",
            "name": "上传失败率(24h)",
            "status": "warn" if upload_fail_rate >= 5 else "ok",
            "value": f"{upload_fail_rate}%",
            "detail": f"失败 {upload_failed} / 总计 {upload_total}",
        }
    )

    anomaly_logs = (
        db.query(ActivityLog)
        .filter(
            ActivityLog.created_at >= day_start,
            ActivityLog.success == 0,
            ActivityLog.action.in_(
                [
                    ActivityAction.LOGIN,
                    ActivityAction.LOGIN_WECHAT,
                    ActivityAction.VIDEO_UPLOAD,
                    ActivityAction.SEND_OTP,
                ]
            ),
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(30)
        .all()
    )

    return {
        "generated_at": now.isoformat(),
        "window_hours": 24,
        "checks": checks,
        "anomalies": [
            {
                "time": log.created_at.isoformat() if log.created_at else None,
                "category": log.category,
                "action": log.action,
                "user_telephone": log.user_telephone,
                "user_role": log.user_role,
                "ip": log.ip_address,
                "error": log.error_msg,
            }
            for log in anomaly_logs
        ],
    }

# ============== 行为统计 ==============

@router.get("/stats/summary")
def get_stats_summary(
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    行为统计汇总

    按分类和行为类型统计数量
    """
    start_date = now_bj() - timedelta(days=days)
    return get_activity_summary(db, start_date=start_date)


@router.get("/stats/trend")
def get_stats_trend(
    category: str = Query(None, description="分类筛选: auth/video/user"),
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    每日趋势统计

    返回每天的操作数量
    """
    return {
        "category": category,
        "days": days,
        "data": get_daily_stats(db, category=category, days=days),
    }


# ============== 行为记录查询 ==============

@router.get("/activities/recent")
def list_recent_activities(
    category: str = Query(None, description="分类: auth/video/user"),
    action: str = Query(None, description="行为: login/video_upload/..."),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    最近的行为记录

    支持按分类和行为类型筛选
    """
    return {
        "items": get_recent_activities(db, category=category, action=action, limit=limit),
    }


@router.get("/activities/auth")
def list_auth_activities(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    认证相关记录

    登录、注册、发送验证码等
    """
    return {
        "items": get_recent_activities(
            db,
            category=ActivityCategory.AUTH,
            limit=limit,
        ),
    }


@router.get("/activities/videos")
def list_video_activities(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    视频相关记录

    上传、删除等
    """
    return {
        "items": get_recent_activities(
            db,
            category=ActivityCategory.VIDEO,
            limit=limit,
        ),
    }


@router.get("/activities/sensitive")
def list_sensitive_activities(
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """
    敏感操作记录

    修改密码、修改权限、修改场地、注册等重要操作
    """
    start_date = now_bj() - timedelta(days=days)
    return {
        "items": get_sensitive_activities(db, start_date=start_date, limit=limit),
    }


# ============== 快捷统计 ==============

@router.get("/quick/otp")
def get_otp_stats(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """验证码发送统计"""
    start_date = now_bj() - timedelta(days=days)

    stats = db.query(
        func.count(ActivityLog.id).label("total"),
        func.sum(ActivityLog.success).label("success"),
    ).filter(
        ActivityLog.action == "send_otp",
        ActivityLog.created_at >= start_date,
    ).first()

    return {
        "days": days,
        "total": stats.total or 0,
        "success": stats.success or 0,
        "failed": (stats.total or 0) - (stats.success or 0),
    }


@router.get("/quick/login")
def get_login_stats(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """登录统计"""
    start_date = now_bj() - timedelta(days=days)

    stats = db.query(
        func.count(ActivityLog.id).label("total"),
        func.sum(ActivityLog.success).label("success"),
    ).filter(
        ActivityLog.action.in_(["login", "login_wechat"]),
        ActivityLog.created_at >= start_date,
    ).first()

    return {
        "days": days,
        "total": stats.total or 0,
        "success": stats.success or 0,
        "failed": (stats.total or 0) - (stats.success or 0),
    }


@router.get("/quick/video-upload")
def get_upload_stats(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    _: User = Depends(require_scope("ops", 1)),
):
    """视频上传统计"""
    start_date = now_bj() - timedelta(days=days)

    stats = db.query(
        func.count(ActivityLog.id).label("total"),
        func.sum(ActivityLog.success).label("success"),
    ).filter(
        ActivityLog.action == "video_upload",
        ActivityLog.created_at >= start_date,
    ).first()

    # 今日上传
    today_start = now_bj().replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.query(func.count(ActivityLog.id)).filter(
        ActivityLog.action == "video_upload",
        ActivityLog.created_at >= today_start,
        ActivityLog.success == 1,
    ).scalar()

    return {
        "days": days,
        "total": stats.total or 0,
        "success": stats.success or 0,
        "failed": (stats.total or 0) - (stats.success or 0),
        "today": today or 0,
    }
