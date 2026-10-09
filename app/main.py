from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging_config import setup_logging, get_logger
from app.core.middleware import RequestLoggingMiddleware
from app.api.auth import router as auth_router
from app.api.invites import router as invites_router
from app.api.videos import router as videos_router
from app.api.users import router as users_router
from app.api.profile import router as profile_router
from app.api.admin_stats import router as admin_stats_router
from app.api.players import router as players_router
from app.api.downl import router as downl_router
from app.api.access_control import router as access_control_router
from app.api.device_logs import router as device_logs_router

# 初始化日志系统（精简版）
setup_logging(
    log_level=settings.LOG_LEVEL,
    log_dir=settings.LOG_DIR,
    app_name=settings.APP_NAME,
)

logger = get_logger(__name__)

app = FastAPI(title=settings.APP_NAME)

# 请求日志中间件
app.add_middleware(RequestLoggingMiddleware)

# 请求校验错误处理
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        f"Validation failed: path={request.url.path} count={len(exc.errors())}"
    )
    return await request_validation_exception_handler(request, exc)

# CORS
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(invites_router, prefix="/invites", tags=["invites"])
app.include_router(videos_router, prefix="/videos", tags=["videos"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(profile_router, prefix="/profile", tags=["profile"])
app.include_router(players_router, prefix="/players", tags=["players"])
app.include_router(admin_stats_router, prefix="/admin", tags=["admin-stats"])
app.include_router(access_control_router, prefix="/admin/access-control", tags=["access-control"])
app.include_router(device_logs_router, prefix="/app", tags=["app-logs"])
app.include_router(downl_router)

# 创建当前环境的本地存储目录。
settings.ensure_storage_dirs()

# 静态资源：视频、缩略图
app.mount("/media", StaticFiles(directory=settings.VIDEO_ROOT), name="media")
app.mount("/thumbs", StaticFiles(directory=settings.THUMB_ROOT), name="thumbs")
app.mount("/download_temp", StaticFiles(directory=settings.VIDEO_TMP_ROOT), name="download_temp")

# Web 前端静态资源
web_dir = Path(__file__).resolve().parent.parent / "web"
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
