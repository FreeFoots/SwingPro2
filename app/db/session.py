# 仅供 init_db 使用；运行期用 core.deps 里的 engine/session
from sqlalchemy import create_engine
from app.core.config import settings

DB_URL = settings.database_url
engine = create_engine(DB_URL, echo=False, future=True)
