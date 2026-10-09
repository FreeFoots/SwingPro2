from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_scope
from app.db.models.user import User
from app.schemas.access_control import (
    RoleScopePolicyItem,
    RoleScopePolicyUpsertRequest,
)
from app.services.access_control import (
    ensure_default_role_scope_policies,
    list_role_scope_policies,
    upsert_role_scope_policy,
)

router = APIRouter()


@router.get("/role-permissions", response_model=list[RoleScopePolicyItem])
def get_role_permissions(
    _: User = Depends(require_scope("policy", 1)),
    db: Session = Depends(get_db),
):
    ensure_default_role_scope_policies(db)
    return list_role_scope_policies(db)


@router.put("/role-permissions", response_model=RoleScopePolicyItem)
def put_role_permission(
    payload: RoleScopePolicyUpsertRequest,
    _: User = Depends(require_scope("policy", 2)),
    db: Session = Depends(get_db),
):
    row = upsert_role_scope_policy(
        db,
        role=payload.role,
        scope_key=payload.scope_key,
        max_level=payload.max_level,
        membership_tier=payload.membership_tier.value if payload.membership_tier else None,
        description=payload.description,
    )
    return row
