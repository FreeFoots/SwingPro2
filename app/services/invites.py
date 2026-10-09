import random, string, datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.db.models.user import InviteCode
from app.core.security import now_bj

# =========================
# 52 进制字符映射
# =========================
BASE52 = string.ascii_uppercase + string.ascii_lowercase  # A=0, ..., z=51

def to_base52(num: int) -> str:
    """十进制转 52 进制"""
    if num == 0:
        return BASE52[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, 52)
        chars.append(BASE52[rem])
    return ''.join(reversed(chars))

def generate_invite_code() -> str:
    """
    生成邀请码规则：
    （01～53）YYMMDDHHMMSS 转 52 进制 → 截取/补齐 8 位
    """
    prefix = f"{random.randint(1, 53):02d}"
    timestamp = now_bj().strftime("%y%m%d%H%M%S")
    base_str = prefix + timestamp
    num = int(base_str)
    code = to_base52(num)
    if len(code) < 8:
        code = code.ljust(8, random.choice(BASE52))
    elif len(code) > 8:
        code = code[-8:]
    return code

# =========================
# 业务逻辑
# =========================
def create_invite(
    db: Session,
    creator_id: str | None,
    *,
    duration_days: int | None = None,
    expired_at: datetime.datetime | None = None,
):
    """生成邀请码，有效期 15 天"""
    code = generate_invite_code()
    if expired_at is None:
        expired_at = now_bj() + datetime.timedelta(days=15)
    duration_days = duration_days or 30
    obj = InviteCode(
        code=code,
        expired_at=expired_at,
        status="unused",
        created_id=creator_id,
        duration_days=duration_days,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def validate_invite(db: Session, code: str) -> InviteCode | None:
    """验证邀请码有效性"""
    obj = db.execute(select(InviteCode).where(InviteCode.code == code)).scalar_one_or_none()
    if not obj or obj.status != "unused":
        return None
    if obj.expired_at and obj.expired_at < now_bj():
        obj.status = "expired"
        db.commit()
        return None
    return obj

def mark_invite_used(db: Session, invite: InviteCode, user_id: str, tel: str):
    """标记邀请码已使用"""
    invite.status = "used"
    invite.user_id = user_id
    invite.telephone = tel
    db.commit()


def expire_outdated_invites(db: Session) -> int:
    """将已过期且仍标记为 unused 的邀请码设为 expired。"""
    now = now_bj()
    updated = (
        db.query(InviteCode)
        .filter(
            InviteCode.status == "unused",
            InviteCode.expired_at.isnot(None),
            InviteCode.expired_at < now,
        )
        .update({"status": "expired"}, synchronize_session=False)
    )
    if updated:
        db.commit()
    return updated


def list_invite_codes(
    db: Session,
    *,
    status: str | None = None,
    creator_id: str | None = None,
    limit: int = 200,
):
    expire_outdated_invites(db)
    query = db.query(InviteCode)
    if creator_id:
        query = query.filter(InviteCode.created_id == creator_id)
    if status and status != "all":
        query = query.filter(InviteCode.status == status)
    query = query.order_by(InviteCode.created_at.desc())
    if limit:
        query = query.limit(limit)
    return query.all()
