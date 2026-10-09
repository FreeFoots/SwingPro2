from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.deps import get_db, require_scope
from app.schemas.auth import InviteCreateRequest, InviteResponse
from app.schemas.invite import InviteListResponse, InviteItem
from app.services.invites import create_invite
from app.services.invites import list_invite_codes
from app.db.models.user import User
from app.services.activity_helper import log_invite_create

router = APIRouter()

@router.get("", response_model=InviteListResponse)
def list_invite_codes_endpoint(
    status: str = Query(default="all", pattern="^(all|unused|used|expired)$"),
    limit: int = Query(default=200, ge=1, le=500),
    current_user: User = Depends(require_scope("invite", 2)),
    db: Session = Depends(get_db),
):
    creator_id = None #if current_user.role == RoleEnum.super_admin else current_user.id
    records = list_invite_codes(db, status=status, creator_id=creator_id, limit=limit)

    used_telephones = {
        obj.telephone for obj in records
        if obj.status == "used" and obj.telephone
    }
    avatar_by_tel: dict[str, str | None] = {}
    if used_telephones:
        rows = db.execute(
            select(User.telephone, User.avatar_url).where(User.telephone.in_(used_telephones))
        ).all()
        avatar_by_tel = {tel: avatar for tel, avatar in rows}

    items = [
        InviteItem(
            code=obj.code,
            status=obj.status,
            expired_at=obj.expired_at,
            duration_days=obj.duration_days,
            telephone=obj.telephone,
            avatar_url=avatar_by_tel.get(obj.telephone) if obj.status == "used" and obj.telephone else None,
            created_at=obj.created_at,
        )
        for obj in records
    ]
    return InviteListResponse(total=len(items), items=items)


@router.post("/create", response_model=InviteResponse)
def create_invite_code(
    request: Request,
    payload: InviteCreateRequest,
    current_user: User = Depends(require_scope("invite", 1)),
    db: Session = Depends(get_db),
):
    """
    生成邀请码：
    - 自动生成 8 位编码
    - 有效期 15 天（北京时间）
    """
    obj = create_invite(
        db,
        creator_id=current_user.id,
        duration_days=payload.duration_days or 30,  # 显式默认值，防止None传入
        expired_at=payload.expired_at,
    )

    # 记录邀请码创建（敏感操作）
    log_invite_create(db, request, current_user, obj.code, success=True)

    return InviteResponse(
        code=obj.code,
        status=obj.status,
        expired_at=obj.expired_at,
        duration_days=obj.duration_days,
    )
