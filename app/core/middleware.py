"""Request summary logging without capturing credentials or upload bodies."""
import time
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.error('%s %s failed', request.method, request.url.path)
            raise
        if request.url.path != '/health' and not request.url.path.startswith(('/media/', '/thumbs/', '/assets/')):
            logger.info('%s %s status=%s duration=%.0fms', request.method, request.url.path,
                        response.status_code, (time.perf_counter() - started) * 1000)
        return response
