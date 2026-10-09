from sqlalchemy.orm import Session

from app.db.models.user import User, RoleEnum, MemberTierEnum, RoleScopePolicy


SCOPE_KEYS = [
    "video",
    "invite",
    "user",
    "players",
    "overview",
    "ops",
    "policy",
]


def _rule(
    role: RoleEnum,
    scope_key: str,
    max_level: int,
    description: str,
    membership_tier: str | None = None,
) -> dict:
    return {
        "role": role,
        "membership_tier": membership_tier,
        "scope_key": scope_key,
        "max_level": int(max_level),
        "description": description,
    }


def _build_default_role_scope_policies() -> list[dict]:
    rows: list[dict] = []

    rows.extend(
        [
            _rule(RoleEnum.user, "video", 2, "普通用户可上传/下载/删除本人视频"),
            _rule(RoleEnum.business, "video", 2, "业务员可上传/下载/删除本人视频"),
            _rule(RoleEnum.admin, "video", 3, "管理员可管理全量视频"),
            _rule(RoleEnum.super_admin, "video", 3, "超级管理员可管理全量视频"),
            _rule(RoleEnum.system_admin, "video", 3, "系统管理员可管理全量视频"),
            _rule(RoleEnum.user, "invite", 0, "普通用户(normal)不可创建邀请码", membership_tier=MemberTierEnum.normal.value),
            _rule(RoleEnum.user, "invite", 0, "普通用户(plus)不可创建邀请码", membership_tier=MemberTierEnum.plus.value),
            _rule(RoleEnum.user, "invite", 1, "普通用户(pro)可创建邀请码", membership_tier=MemberTierEnum.pro.value),
            _rule(RoleEnum.user, "invite", 1, "普通用户(ultra)可创建邀请码", membership_tier=MemberTierEnum.ultra.value),
            _rule(RoleEnum.business, "invite", 1, "业务员可创建邀请码"),
            _rule(RoleEnum.admin, "invite", 2, "管理员可创建并查看邀请码"),
            _rule(RoleEnum.super_admin, "invite", 2, "超级管理员可创建并查看邀请码"),
            _rule(RoleEnum.system_admin, "invite", 2, "系统管理员可创建并查看邀请码"),
            _rule(RoleEnum.admin, "user", 2, "管理员可管理用户"),
            _rule(RoleEnum.super_admin, "user", 2, "超级管理员可管理用户"),
            _rule(RoleEnum.system_admin, "user", 2, "系统管理员可管理用户"),
            _rule(RoleEnum.user, "players", 1, "普通用户可搜索打球人"),
            _rule(RoleEnum.business, "players", 1, "业务员可搜索打球人"),
            _rule(RoleEnum.admin, "players", 1, "管理员可搜索打球人"),
            _rule(RoleEnum.super_admin, "players", 1, "超级管理员可搜索打球人"),
            _rule(RoleEnum.system_admin, "players", 1, "系统管理员可搜索打球人"),
            _rule(RoleEnum.admin, "overview", 1, "管理员可查看业务概览"),
            _rule(RoleEnum.super_admin, "overview", 1, "超级管理员可查看业务概览"),
            _rule(RoleEnum.system_admin, "overview", 1, "系统管理员可查看业务概览"),
            _rule(RoleEnum.system_admin, "ops", 1, "系统管理员可访问系统检查与行为统计"),
            _rule(RoleEnum.system_admin, "policy", 2, "系统管理员可读写权限策略"),
        ]
    )

    configured_scopes = {row["scope_key"] for row in rows}
    missing_scopes = [key for key in SCOPE_KEYS if key not in configured_scopes]
    if missing_scopes:
        raise RuntimeError(f"Missing default scope rows: {', '.join(missing_scopes)}")

    return rows


DEFAULT_ROLE_SCOPE_POLICIES = _build_default_role_scope_policies()
_DEFAULT_POLICIES_ENSURED = False


def _normalize_tier_for_policy(role: RoleEnum, membership_tier: str | None) -> str | None:
    if role in (RoleEnum.user, RoleEnum.business):
        if not membership_tier:
            return None
        if membership_tier not in {m.value for m in MemberTierEnum}:
            raise ValueError("INVALID_MEMBERSHIP_TIER")
        return membership_tier
    return None


def ensure_default_role_scope_policies(db: Session) -> None:
    """初始化默认分级策略；仅补充缺失项，不覆盖已有策略。"""
    global _DEFAULT_POLICIES_ENSURED
    if _DEFAULT_POLICIES_ENSURED:
        return

    created = 0
    for item in DEFAULT_ROLE_SCOPE_POLICIES:
        tier = _normalize_tier_for_policy(item["role"], item.get("membership_tier"))
        exists = (
            db.query(RoleScopePolicy.id)
            .filter(
                RoleScopePolicy.role == item["role"],
                RoleScopePolicy.scope_key == item["scope_key"],
                RoleScopePolicy.membership_tier == tier,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            RoleScopePolicy(
                role=item["role"],
                membership_tier=tier,
                scope_key=item["scope_key"],
                max_level=int(item["max_level"]),
                description=item.get("description"),
            )
        )
        created += 1

    if created:
        db.commit()

    _DEFAULT_POLICIES_ENSURED = True


def upsert_role_scope_policy(
    db: Session,
    *,
    role: RoleEnum,
    scope_key: str,
    max_level: int,
    membership_tier: str | None = None,
    description: str | None = None,
) -> RoleScopePolicy:
    tier = _normalize_tier_for_policy(role, membership_tier)
    if scope_key not in SCOPE_KEYS:
        raise ValueError("INVALID_SCOPE_KEY")

    row = (
        db.query(RoleScopePolicy)
        .filter(
            RoleScopePolicy.role == role,
            RoleScopePolicy.scope_key == scope_key,
            RoleScopePolicy.membership_tier == tier,
        )
        .first()
    )
    if row:
        row.max_level = max(0, int(max_level))
        row.description = description
    else:
        row = RoleScopePolicy(
            role=role,
            membership_tier=tier,
            scope_key=scope_key,
            max_level=max(0, int(max_level)),
            description=description,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return row


def list_role_scope_policies(db: Session) -> list[RoleScopePolicy]:
    ensure_default_role_scope_policies(db)
    return (
        db.query(RoleScopePolicy)
        .order_by(RoleScopePolicy.role.asc(), RoleScopePolicy.membership_tier.asc().nullsfirst(), RoleScopePolicy.scope_key.asc())
        .all()
    )


def _resolve_user_tier(user: User) -> str | None:
    if user.role not in (RoleEnum.user, RoleEnum.business):
        return None
    tier = user.membership_tier or MemberTierEnum.normal.value
    if tier not in {m.value for m in MemberTierEnum}:
        return MemberTierEnum.normal.value
    return tier


def get_user_scope_level(db: Session, *, user: User, scope_key: str) -> int:
    """获取用户在某权限域中的最高等级。"""
    ensure_default_role_scope_policies(db)

    if scope_key not in SCOPE_KEYS:
        return 0

    tier = _resolve_user_tier(user)
    if tier is not None:
        specific = (
            db.query(RoleScopePolicy)
            .filter(
                RoleScopePolicy.role == user.role,
                RoleScopePolicy.membership_tier == tier,
                RoleScopePolicy.scope_key == scope_key,
            )
            .first()
        )
        if specific:
            return max(0, int(specific.max_level or 0))

    wildcard = (
        db.query(RoleScopePolicy)
        .filter(
            RoleScopePolicy.role == user.role,
            RoleScopePolicy.membership_tier.is_(None),
            RoleScopePolicy.scope_key == scope_key,
        )
        .first()
    )
    if wildcard:
        return max(0, int(wildcard.max_level or 0))

    return 0


def user_has_scope_level(db: Session, *, user: User, scope_key: str, min_level: int) -> bool:
    """判断用户在某权限域是否达到所需等级。"""
    return get_user_scope_level(db, user=user, scope_key=scope_key) >= max(0, int(min_level))
