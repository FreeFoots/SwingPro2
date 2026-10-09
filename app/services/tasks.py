import os
import subprocess
import json
import mimetypes
from sqlalchemy.orm import configure_mappers
from app.core.deps import SessionLocal
from app.db.models.user import User  # ensure metadata registers app_user table
from app.db.models.video import Video
from app.core.celery_app import celery_app
from app.core.security import now_bj, BEIJING_TZ
from app.core.config import settings

celery_app.autodiscover_tasks(['app.services'])

configure_mappers()
@celery_app.task(name="analyze_video_metadata")
# def _build_thumb_storage_path(video: Video) -> str:
#     timestamp = video.created_at or now_bj()
#     if timestamp.tzinfo is None:
#         timestamp = timestamp.replace(tzinfo=BEIJING_TZ)
#     else:
#         timestamp = timestamp.astimezone(BEIJING_TZ)
#     thumb_dir = build_date_directory(settings.THUMB_ROOT, timestamp)
#     filename = f"{os.path.splitext(os.path.basename(video.file_path))[0]}.jpg"
#     return resolve_unique_path(thumb_dir, filename)


def analyze_video_metadata(video_id: int):
    """异步分析视频元数据并更新数据库"""
    db = SessionLocal()
    video = db.get(Video, video_id)
    if not video or not os.path.exists(video.file_path):
        return

    try:
        # 使用 ffprobe 获取元数据 (轻量级，无需加载整个视频)
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,duration,nb_frames",
            "-of", "json",
            video.file_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        meta = {}
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data.get("streams"):
                    meta = data["streams"][0]
            except json.JSONDecodeError:
                pass

        # 解析 FPS
        fps_str = meta.get("avg_frame_rate", "0/0")
        fps = 0.0
        if "/" in fps_str:
            num, den = fps_str.split("/")
            if float(den) > 0:
                fps = float(num) / float(den)
        else:
            fps = float(fps_str) if fps_str else 0.0

        # 帧率异常检测与修正 (例如 600fps 可能是错误的时间基准)
        if fps > 400:
            fps = 30.0  # 回退到标准帧率

        # 解析时长
        duration_sec = meta.get("duration")
        if duration_sec:
            duration = int(float(duration_sec))
        else:
            # 尝试通过帧数计算
            nb_frames = meta.get("nb_frames")
            if nb_frames and fps > 0:
                duration = int(float(nb_frames) / fps)
            else:
                duration = 0

        width = meta.get("width")
        height = meta.get("height")
        resolution = f"{width}x{height}" if width and height else None

        size_bytes = os.path.getsize(video.file_path)
        mime_type = mimetypes.guess_type(video.file_path)[0] or "video/quicktime"

        # 生成封面图（如果不存在）
        thumb_path = video.thumb_path
        if not thumb_path or not os.path.exists(thumb_path):
            video_basename = os.path.splitext(os.path.basename(video.file_path))[0]
            video_dir = os.path.dirname(video.file_path)
            # 保持目录结构
            date_parts = video_dir.replace(settings.VIDEO_ROOT, '').strip('/')
            thumb_dir = os.path.join(settings.THUMB_ROOT, date_parts)
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_path = os.path.join(thumb_dir, f"{video_basename}_thumb.jpg")

            # 使用 ffmpeg 快速抽取中间帧或第一帧
            # -ss 0.1 跳过黑屏首帧
            cmd_thumb = [
                "ffmpeg", "-y",
                "-ss", "0.1",
                "-i", video.file_path,
                "-vframes", "1",
                "-vf", "scale=720:-1",  # 限制宽度，优化体积
                "-q:v", "5",            # JPEG 质量
                thumb_path
            ]
            subprocess.run(cmd_thumb, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 更新数据库
        video.fps = fps
        video.duration = duration
        video.resolution = resolution
        video.size_bytes = size_bytes
        video.fps = fps
        video.duration = duration
        video.resolution = resolution
        video.size_bytes = size_bytes
        if not video.mime_type:
            video.mime_type = mime_type
        video.thumb_path = thumb_path
        if not video.title:
            created_time = video.created_at or now_bj()
            if created_time.tzinfo is None:
                created_time = created_time.replace(tzinfo=BEIJING_TZ)
            else:
                created_time = created_time.astimezone(BEIJING_TZ)
            video.title = created_time.strftime("%Y-%m-%d %H:%M:%S")
        video.status = "finished"
        db.commit()

    except Exception as e:
        db.rollback()
        failed_video = db.get(Video, video_id)
        if failed_video:
            failed_video.status = "failed"
            db.commit()
        print(f"❌ 视频分析失败：{e}")
    finally:
        db.close()
