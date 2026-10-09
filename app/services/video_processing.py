import os
import re
import subprocess
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from app.core.config import settings
from app.core.security import now_bj


FILENAME_PATTERN = re.compile(r"(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})__(\d+)__([0-9A-F-]+)", re.IGNORECASE)
MOV_EXTENSIONS = {".mov", ".qt", ".quicktime"}
TARGET_EXT = ".mov"
TARGET_MIME = "video/quicktime"


@dataclass
class ProcessedVideo:
    video_path: str
    thumbnail_path: Optional[str]
    size_bytes: int
    mime_type: str
    captured_at: datetime


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def normalize_filename(original_name: str) -> tuple[str, datetime]:
    base, _ = os.path.splitext(original_name)
    match = FILENAME_PATTERN.match(base)
    if not match:
        timestamp = now_bj()
        safe_name = f"{timestamp.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return safe_name, timestamp

    year, month, day, hour, minute, second, seq, raw_uuid = match.groups()
    formatted = f"{year}{month}{day}{hour}{minute}{second}_{seq}_{raw_uuid}"
    timestamp = datetime.strptime(f"{year}{month}{day}{hour}{minute}{second}", "%Y%m%d%H%M%S")
    tz = now_bj().tzinfo
    if tz and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=tz)
    return formatted, timestamp


def build_date_directory(base_path: str, timestamp: datetime) -> str:
    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    day = timestamp.strftime("%d")

    year_path = os.path.join(base_path, year)
    month_path = os.path.join(year_path, month)
    day_path = os.path.join(month_path, day)
    ensure_dir(year_path)
    ensure_dir(month_path)
    ensure_dir(day_path)
    return day_path


def resolve_unique_path(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{counter}{ext}"
        counter += 1
    return os.path.join(directory, candidate)


def generate_thumbnail(video_path: str, thumbnail_path: str) -> Optional[str]:
    try:
        ensure_dir(os.path.dirname(thumbnail_path))
        temp_name = f"temp_{uuid.uuid4().hex[:8]}.jpg"
        temp_path = os.path.join(os.path.dirname(thumbnail_path), temp_name)
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-ss", "00:00:00",
            "-vframes", "1",
            temp_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        with Image.open(temp_path) as img:
            base_width = 720
            w_percent = base_width / float(img.size[0])
            h_size = int(float(img.size[1]) * w_percent)
            resample_filter = getattr(Image, "Resampling", Image).LANCZOS
            resized = img.resize((base_width, h_size), resample_filter)
            resized.save(thumbnail_path, "JPEG", quality=85)
        os.remove(temp_path)
        return thumbnail_path
    except Exception:
        return None


def _convert_to_mov(src_path: str, dst_path: str) -> None:
    ensure_dir(os.path.dirname(dst_path))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-f",
            "mov",
            dst_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def process_upload_file(upload_file, video_root: Optional[str] = None, thumb_root: Optional[str] = None, tmp_root: Optional[str] = None) -> ProcessedVideo:
    video_root = video_root or settings.VIDEO_ROOT
    thumb_root = thumb_root or settings.THUMB_ROOT

    original_name = upload_file.filename or f"upload_{uuid.uuid4().hex}"
    normalized_name, timestamp = normalize_filename(original_name)

    video_dir = build_date_directory(video_root, timestamp)
    thumb_dir = build_date_directory(thumb_root, timestamp)

    ext = os.path.splitext(original_name)[1] or TARGET_EXT
    ext_lower = ext.lower()
    is_mov = ext_lower in MOV_EXTENSIONS or ext_lower == TARGET_EXT
    target_filename = f"{normalized_name}{TARGET_EXT}"
    final_video_path = resolve_unique_path(video_dir, target_filename)

    raw_ext = TARGET_EXT if is_mov else (ext_lower if ext_lower.startswith(".") else f".{ext_lower}")
    raw_filename = f"{normalized_name}{raw_ext}"
    raw_video_path = final_video_path if raw_ext == TARGET_EXT else resolve_unique_path(video_dir, raw_filename)

    ensure_dir(os.path.dirname(raw_video_path))
    try:
        try:
            upload_file.file.seek(0)
        except (AttributeError, OSError):
            pass
        with open(raw_video_path, "wb") as buffer:
            for chunk in iter(lambda: upload_file.file.read(1024 * 1024), b""):
                buffer.write(chunk)
    except Exception:
        if os.path.exists(raw_video_path):
            try:
                os.remove(raw_video_path)
            except OSError:
                pass
        raise

    output_path = raw_video_path
    mime_type = upload_file.content_type or TARGET_MIME

    if not is_mov or raw_ext != TARGET_EXT:
        try:
            _convert_to_mov(raw_video_path, final_video_path)
            output_path = final_video_path
            mime_type = TARGET_MIME
        finally:
            if os.path.exists(raw_video_path) and raw_video_path != output_path:
                try:
                    os.remove(raw_video_path)
                except OSError:
                    pass
    else:
        output_path = final_video_path

    size_bytes = os.path.getsize(output_path)
    mime_type = TARGET_MIME
    thumb_base = os.path.splitext(os.path.basename(output_path))[0]
    thumbnail_path = os.path.join(thumb_dir, f"{thumb_base}_thumb.jpg")
    thumb_result = generate_thumbnail(output_path, thumbnail_path)

    return ProcessedVideo(
        video_path=output_path,
        thumbnail_path=thumb_result,
        size_bytes=size_bytes,
        mime_type=mime_type,
        captured_at=timestamp,
    )
