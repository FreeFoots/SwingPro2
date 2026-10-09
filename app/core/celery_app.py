from celery import Celery
from app.core.config import settings

celery_app = Celery(
    settings.APP_NAME,
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=False,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    beat_schedule={},
)

celery_app.autodiscover_tasks(["app.services"])
