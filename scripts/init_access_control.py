"""
初始化会员体系与角色分级权限策略表

用途：
1. 为 app_user 增加 membership_tier 字段（若不存在）；
2. 创建 role_scope_policy 表；
3. 写入默认权限策略。
"""

from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine
from app.db.models import user  # noqa: F401  # 确保模型已注册
from app.services.access_control import ensure_default_role_scope_policies
from app.core.deps import SessionLocal


def migrate_user_membership_tier() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE app_user
                ADD COLUMN IF NOT EXISTS membership_tier VARCHAR(16)
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE app_user
                SET membership_tier = 'normal'
                WHERE role IN ('user', 'business')
                  AND (membership_tier IS NULL OR membership_tier = '' OR membership_tier NOT IN ('normal', 'plus', 'pro', 'ultra'))
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app_user
                ALTER COLUMN membership_tier DROP NOT NULL
                """
            )
        )
        conn.execute(
            text(
                """
                UPDATE app_user
                SET membership_tier = NULL
                WHERE role IN ('admin', 'super_admin', 'system_admin')
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE app_user
                ALTER COLUMN membership_tier SET DEFAULT 'normal'
                """
            )
        )


def main() -> None:
    migrate_user_membership_tier()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_default_role_scope_policies(db)
    finally:
        db.close()

    print("✅ Access control initialized.")


if __name__ == "__main__":
    main()
