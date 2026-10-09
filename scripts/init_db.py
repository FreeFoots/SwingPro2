from app.db.base import Base
from app.db.session import engine
from app.db.models import user, video, activity

from app.core.deps import SessionLocal
from app.services.access_control import ensure_default_role_scope_policies

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_default_role_scope_policies(db)
    finally:
        db.close()

    print("✅ Tables created.")
