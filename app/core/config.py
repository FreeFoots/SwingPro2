"""Environment-only configuration, without deployment credentials."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / '.env', override=False)


class Settings(BaseModel):
    model_config = ConfigDict(validate_default=True)
    APP_NAME: str = 'SwingPro2'
    PG_HOST: str = '127.0.0.1'
    PG_PORT: int = Field(default=5432, ge=1, le=65535)
    PG_USER: str = 'swingpro2'
    PG_PASSWORD: str
    PG_DB: str = 'swingpro2'
    REDIS_URL: str | None = 'redis://127.0.0.1:6379/0'
    JWT_SECRET: str
    JWT_ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    OTP_TTL_SECONDS: int = Field(default=300, gt=0)
    OTP_SEND_COOLDOWN_SECONDS: int = Field(default=60, gt=0)
    OTP_DAILY_LIMIT: int = Field(default=10, gt=0)
    FIELD_BIND_CODE_EXPIRES_SECONDS: int = Field(default=300, gt=0)
    FIELD_BIND_DURATION_SECONDS: int = Field(default=3600, gt=0)
    CORS_ORIGINS: list[str] = Field(default_factory=list)
    CELERY_BROKER_URL: str = 'redis://127.0.0.1:6379/1'
    CELERY_RESULT_BACKEND: str = 'redis://127.0.0.1:6379/2'
    CELERY_TIMEZONE: str = 'Asia/Shanghai'
    CELERY_TASK_ALWAYS_EAGER: bool = False
    VIDEO_ROOT: str = 'storage/videos'
    THUMB_ROOT: str = 'storage/thumbs'
    VIDEO_TMP_ROOT: str = 'storage/download_temp'
    DRAW_JSON_ROOT: str = 'storage/drawings'
    WECHAT_APP_ID: str = ''
    WECHAT_APP_SECRET: str = ''
    WECHAT_WEB_ID: str = ''
    WECHAT_WEB_SECRET: str = ''
    WECHAT_REDIRECT_URI: str = ''
    WECHAT_STATE_PREFIX: str = ''
    WEB_PLATFORM_URL: str = 'http://127.0.0.1:8000/platform.html'
    SMS_PROVIDER: str = 'local'
    SMS_SPUG_URL: str = ''
    SMS_ALIYUN_ACCESS_KEY_ID: str = ''
    SMS_ALIYUN_ACCESS_KEY_SECRET: str = ''
    SMS_ALIYUN_SIGN_NAME: str = ''
    SMS_ALIYUN_TEMPLATE_CODE: str = ''
    LOG_LEVEL: str = 'INFO'
    LOG_DIR: str = 'logs'

    @field_validator('PG_PASSWORD', 'JWT_SECRET')
    @classmethod
    def require_real_secret(cls, value: str) -> str:
        if not value.strip() or value.startswith('replace-'):
            raise ValueError('Set a private value in .env or the process environment')
        return value

    @field_validator('JWT_SECRET')
    @classmethod
    def require_long_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError('JWT_SECRET must contain at least 32 characters')
        return value

    @field_validator('CORS_ORIGINS', mode='before')
    @classmethod
    def parse_origins(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value.strip().startswith('[') else [x.strip() for x in value.split(',') if x.strip()]
        return value

    @field_validator('REDIS_URL', mode='before')
    @classmethod
    def optional_redis(cls, value):
        return value or None

    @field_validator('VIDEO_ROOT', 'THUMB_ROOT', 'VIDEO_TMP_ROOT', 'DRAW_JSON_ROOT', 'LOG_DIR')
    @classmethod
    def resolve_project_path(cls, value: str) -> str:
        path = Path(value).expanduser()
        return str(path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve())

    @property
    def database_url(self) -> URL:
        return URL.create('postgresql+psycopg2', username=self.PG_USER, password=self.PG_PASSWORD,
                          host=self.PG_HOST, port=self.PG_PORT, database=self.PG_DB)

    def ensure_storage_dirs(self) -> None:
        for directory in (self.VIDEO_ROOT, self.THUMB_ROOT, self.VIDEO_TMP_ROOT, self.DRAW_JSON_ROOT):
            Path(directory).mkdir(parents=True, exist_ok=True)


settings = Settings(**{key: os.environ[key] for key in Settings.model_fields if key in os.environ})
