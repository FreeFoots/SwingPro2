import os
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.logging_config import get_logger


router = APIRouter()
logger = get_logger(__name__)


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_LOG_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "logs_app"


def _sanitize_name(raw: str | None, fallback: str) -> str:
    text = (raw or "").strip()
    if not text:
        return fallback
    text = os.path.basename(text)
    text = _SAFE_NAME_RE.sub("_", text)
    text = text.strip()
    return text or fallback


@router.post("/log")
async def upload_device_log(
    device_id: str = Form(..., min_length=1, max_length=128, description="设备码"),
    log_file: UploadFile = File(..., description="日志文件"),
):
    """接收 App 端设备日志：保存到 logs_app/，文件名为 device_id + 原文件名。"""
    safe_device_id = _sanitize_name(device_id, "unknown_device")
    source_name = _sanitize_name(log_file.filename, "device.log")
    target_name = f"{safe_device_id}{source_name}"

    _LOG_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = _LOG_UPLOAD_DIR / target_name

    written = 0
    try:
        with open(target_path, "wb") as output:
            while True:
                chunk = await log_file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                written += len(chunk)
    except Exception as exc:
        logger.error("save device log failed device_id=%s filename=%s err=%s", safe_device_id, source_name, exc)
        raise HTTPException(status_code=500, detail="日志文件保存失败")
    finally:
        await log_file.close()

    if written <= 0:
        try:
            if target_path.exists():
                target_path.unlink()
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="日志文件不能为空")

    return {
        "ok": True,
        "device_id": safe_device_id,
        "filename": target_name,
        "size_bytes": written,
        "saved_path": str(target_path),
    }
