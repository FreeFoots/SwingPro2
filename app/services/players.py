"""
常用打球人服务模块
"""
from sqlalchemy.orm import Session
from sqlalchemy import select
from fastapi import HTTPException

from app.db.models.user import Player, User
from app.services.wechat import get_wechat_user_detail
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def get_player_by_unionid(db: Session, owner_id: str, wechat_unionid: str) -> Player | None:
    """根据 unionid 获取常用打球人"""
    stmt = select(Player).where(
        Player.owner_id == owner_id,
        Player.wechat_unionid == wechat_unionid,
    )
    return db.execute(stmt).scalar_one_or_none()


def get_players(db: Session, owner_id: str) -> list[Player]:
    """获取用户的常用打球人列表"""
    stmt = select(Player).where(
        Player.owner_id == owner_id
    ).order_by(Player.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def create_player(
    db: Session,
    owner_id: str,
    wechat_unionid: str,
    name: str,
    avatar_url: str | None = None,
    active: bool = False,
    is_self: bool = False,
) -> Player:
    """创建常用打球人"""
    # 强制不使用 active 功能，恒为 False
    player = Player(
        owner_id=owner_id,
        wechat_unionid=wechat_unionid,
        name=name,
        avatar_url=avatar_url,
        active=False,
        is_self=is_self,
    )
    db.add(player)
    db.commit()
    db.refresh(player)
    return player


def delete_player(db: Session, owner_id: str, player_id: int) -> bool:
    """删除常用打球人"""
    stmt = select(Player).where(
        Player.id == player_id,
        Player.owner_id == owner_id,
    )
    player = db.execute(stmt).scalar_one_or_none()
    if not player:
        return False
    db.delete(player)
    db.commit()
    return True


def add_wechat_profile(
    db: Session,
    owner_id: str,
    wechat_unionid: str,
    nickname: str | None = None,
    avatar_url: str | None = None,
    is_self: bool = False,
    active: bool = False,
):
    """
    将微信用户添加为常用打球人
    返回: (player, error)
    """
    existing_user = db.execute(
        select(User).where(User.wechat_unionid == wechat_unionid)
    ).scalar_one_or_none()

    if existing_user and is_self and existing_user.id != owner_id:
        return None, "WECHAT_IS_MAIN_USER"

    existing_player = db.execute(
        select(Player).where(
            Player.owner_id == owner_id,
            Player.wechat_unionid == wechat_unionid,
        )
    ).scalar_one_or_none()

    if existing_player:
        changed = False
        if is_self and not getattr(existing_player, "is_self", False):
            existing_player.is_self = True
            changed = True

        # 停用 active 自动设置功能
        # if active and not existing_player.active:
        #     existing_player.active = True
        #     changed = True

        if changed:
            db.commit()
        return existing_player, "ALREADY_EXISTS"

    player = create_player(
        db=db,
        owner_id=owner_id,
        wechat_unionid=wechat_unionid,
        name=nickname or "微信用户",
        avatar_url=avatar_url,
        is_self=is_self,
        active=active,
    )
    return player, None


def set_active_player(
    db: Session,
    owner_id: str,
    wechat_unionid: str,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> Player:
    """
    将某个常用打球人设为当前活跃，取消该 owner 其他 active
    如不存在则先创建
    """
    players = db.execute(
        select(Player).where(Player.owner_id == owner_id)
    ).scalars().all()
    target = None
    for p in players:
        if p.wechat_unionid == wechat_unionid:
            target = p
        # 强制清除 active 状态
        if p.active:
            p.active = False

    if not target:
        target = create_player(
            db=db,
            owner_id=owner_id,
            wechat_unionid=wechat_unionid,
            name=nickname or "微信用户",
            avatar_url=avatar_url,
            active=False,
        )
    else:
        target.name = nickname or target.name
        target.avatar_url = avatar_url or target.avatar_url
        target.active = False
        db.commit()
        db.refresh(target)
    return target


def deactivate_active_players(db: Session, owner_id: str) -> None:
    """将某个用户的所有打球人 active 置为 False"""
    players = db.execute(
        select(Player).where(Player.owner_id == owner_id)
    ).scalars().all()
    changed = False
    for p in players:
        if p.active:
            p.active = False
            changed = True
    if changed:
        db.commit()


async def add_player_from_wechat(
    db: Session,
    owner_id: str,
    wechat_unionid: str,
    nickname: str,
    avatar_url: str | None,
    is_self: bool = False,
) -> tuple[Player, list[Player], str]:
    """
    添加常用打球人（已获取微信信息）
    返回: (player, updated_list, result_code)
    result_code: "CREATED" | "UPDATED" | "ALREADY_EXISTS"
    """
    if not wechat_unionid:
        raise HTTPException(status_code=400, detail="无法获取微信用户信息")

    existing = get_player_by_unionid(db, owner_id, wechat_unionid)
    if existing:
        existing.name = nickname
        existing.avatar_url = avatar_url
        if is_self and not getattr(existing, "is_self", False):
            existing.is_self = True
        db.commit()
        db.refresh(existing)
        players = get_players(db, owner_id)
        # 即使更新了资料，业务上也属于“已存在/重复添加”
        return existing, players, "ALREADY_EXISTS"

    player = create_player(
        db=db,
        owner_id=owner_id,
        wechat_unionid=wechat_unionid,
        name=nickname,
        avatar_url=avatar_url,
        is_self=is_self,
    )

    logger.info(
        f"成功添加常用打球人: owner={owner_id}, unionid={wechat_unionid}, name={nickname}"
    )

    players = get_players(db, owner_id)
    return player, players, "CREATED"


async def scan_add_player(db: Session, owner_id: str, code: str) -> tuple[Player, list[Player]]:
    """
    (已废弃，请使用 add_player_from_wechat) 扫码添加常用打球人
    """
    try:
        wechat_info = await get_wechat_user_detail(code)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取微信用户信息失败: {e}")
        raise HTTPException(status_code=400, detail="获取微信用户信息失败")

    player, players, _ = await add_player_from_wechat(
        db,
        owner_id,
        wechat_info.get("unionid"),
        wechat_info.get("nickname", "未知用户"),
        wechat_info.get("avatar_url"),
    )
    return player, players
