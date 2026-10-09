"""
常用打球人 API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List
import uuid
import json

from app.core.deps import get_db, get_current_user, get_redis, require_scope
from app.core.config import settings
from app.db.models.user import User, Player
from app.schemas.player import (
    PlayerJoinRequest,
    PlayerJoinResponse,
    PlayerListResponse,
    PlayerOut,
)
from app.schemas.auth import QRLoginCreateResponse
from app.services.players import (
    get_players,
    delete_player,
    add_player_from_wechat,
    set_active_player as set_active_player_record,
    deactivate_active_players,
)
from app.services.wechat import web_qr_key, build_web_qr_url, extract_qr_image, WEB_QR_TTL, get_wechat_web_user_info

router = APIRouter()

@router.get("/search", response_model=List[PlayerOut])
def search_players_endpoint(
    q: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope("players", 1))
):
    """
    Search players by name (WeChat nickname)
    Returns distinct players by wechat_unionid
    """
    keyword = (q or "").strip()

    # distinct on unionid, picking one representative
    base_query = db.query(
        Player.wechat_unionid,
        func.max(Player.id).label('max_id')
    ).filter(
        Player.wechat_unionid.isnot(None),
        Player.wechat_unionid != "",
    )
    if keyword:
        base_query = base_query.filter(Player.name.like(f"%{keyword}%"))

    subquery = base_query.group_by(Player.wechat_unionid).subquery()

    players = db.query(Player).join(
        subquery, Player.id == subquery.c.max_id
    ).order_by(Player.name.asc(), Player.id.desc()).limit(limit).all()

    return players


# =========================
# 当前打球人（单用户仅一个）
# =========================
class ActivePlayerRequest(BaseModel):
    user_id: str
    wechat_unionid: str | None = None

@router.post("/active")
async def set_active_player(
    payload: ActivePlayerRequest,
    db: Session = Depends(get_db),
):
    """
    选中当前打球人（微信成员），每个用户仅一个活跃打球人
    开放接口：无需登录，需传入 user_id 和 wechat_unionid
    """
    # 1. 获取用户信息，判断角色
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    unionid = payload.wechat_unionid

    # 3. unionid 为空则清空当前 active
    if not unionid:
        deactivate_active_players(db, payload.user_id)
        data = {
            "wechat_unionid": None,
            "nickname": None,
            "avatar_url": None,
            "owner_id": payload.user_id,
            "updated_by": payload.user_id,
        }
        return {"ok": True, "active_player": data}

    # 4. 为指定用户设置唯一活跃打球人
    player = set_active_player_record(db, payload.user_id, unionid)

    data = {
        "wechat_unionid": player.wechat_unionid,
        "nickname": player.name,
        "avatar_url": player.avatar_url,
        "owner_id": player.owner_id,
        "updated_by": payload.user_id, # 模拟 updated_by
    }
    return {"ok": True, "active_player": data}


# =========================
# 生成邀请二维码（需要登录）
# =========================
@router.post("/invite", response_model=QRLoginCreateResponse)
async def create_player_invite(
    current_user: User = Depends(get_current_user),
    r=Depends(get_redis)
):
    """
    生成常用打球人邀请二维码 (网站扫码模式)

    返回 qr_token 和 qrcode_url。
    前端展示二维码，并轮询 /auth/wechat_web/poll?qr_token=xxx&mode=invite_player
    """
    if not settings.WECHAT_WEB_ID or not settings.WECHAT_WEB_SECRET:
        raise HTTPException(status_code=500, detail="未配置微信网站应用参数")

    token = uuid.uuid4().hex
    await r.set(
        web_qr_key("invite_player", token),
        json.dumps({"status": "pending", "owner_id": current_user.id}),
        ex=WEB_QR_TTL,
    )
    url = build_web_qr_url("invite_player", token)

    qr_image_url = await extract_qr_image(url)

    return QRLoginCreateResponse(
        qr_token=token,
        expires_in=WEB_QR_TTL,
        qrcode_url=url,
        qr_image_url=qr_image_url
    )


@router.get("/info", response_model=PlayerListResponse)
async def list_players(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的常用打球人列表"""
    players = get_players(db, current_user.id)
    active_unionid = next((p.wechat_unionid for p in players if getattr(p, "active", False)), None)
    return PlayerListResponse(
        total=len(players),
        items=[PlayerOut.model_validate(p) for p in players],
        active_wechat_unionid=active_unionid
    )


# =========================
# 微信用户扫码加入常用打球人（无需登录）
# =========================
@router.post("/join", response_model=PlayerJoinResponse)
async def join_player(
    payload: PlayerJoinRequest,
    db: Session = Depends(get_db)
):
    """
    微信用户扫码加入常用打球人

    回调页获取 URL 的 code（微信授权码）和 state（邀请人ID），再调用此接口完成添加。
    """
    owner = db.get(User, payload.user_id)
    if not owner:
        return PlayerJoinResponse(success=False, message="邀请人不存在")

    try:
        # 使用 Web 应用配置获取用户信息
        wx_info = await get_wechat_web_user_info(payload.wechat_code)
        unionid = wx_info.get("unionid")
        print("微信用户信息：", wx_info)
        if not unionid:
            return PlayerJoinResponse(success=False, message="无法获取微信用户信息")

        player, players, status = await add_player_from_wechat(
            db,
            payload.user_id,
            unionid,
            wx_info.get("nickname", "未知用户"),
            wx_info.get("avatar_url")
        )
        print(f"添加常用打球人结果：player={player}, status={status}")

        msg = "添加成功"
        if status == "ALREADY_EXISTS":
            msg = "用户重复扫码加入"

        return PlayerJoinResponse(
            success=True,
            message=msg,
            player=PlayerOut.model_validate(player),
            players=[PlayerOut.model_validate(p) for p in players]
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "添加失败"
        if detail == "WECHAT_IS_MAIN_USER":
            return PlayerJoinResponse(success=False, message="该微信已绑定为主账号，无法添加")
        return PlayerJoinResponse(success=False, message=detail)
    except Exception:
        return PlayerJoinResponse(success=False, message="添加失败")


@router.delete("/{player_id}")
def remove_player(
    player_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除常用打球人"""
    success = delete_player(db, current_user.id, player_id)
    if not success:
        raise HTTPException(status_code=404, detail="常用打球人不存在")
    return {"message": "删除成功"}
