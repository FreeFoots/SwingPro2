"""
微信服务模块（统一使用真实微信 API）

说明：
- 统一依赖官方接口获取用户信息，移除 local 模拟模式；
- 所有下游调用请优先使用 unionid 作为唯一标识，若 unionid 不存在再回退 unionid。
"""

import httpx
from fastapi import HTTPException
from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)
# ============== 真实微信API模式 ==============

async def _get_wechat_user_info_real(code: str) -> dict:
    """真实微信API：获取用户基础信息（移动/公众号应用）"""
    if not settings.WECHAT_APP_ID or not settings.WECHAT_APP_SECRET:
        raise HTTPException(status_code=500, detail="服务器未配置微信参数")

    url = "https://api.weixin.qq.com/sns/oauth2/access_token"
    params = {
        "appid": settings.WECHAT_APP_ID,
        "secret": settings.WECHAT_APP_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params)
            data = resp.json()
        except Exception as e:
            logger.error(f"[微信] API请求失败: {e}")
            raise HTTPException(status_code=500, detail=f"微信 API 请求失败: {str(e)}")

    if "errcode" in data and data["errcode"] != 0:
        logger.error(f"[微信] 授权失败: {data}")
        raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg')}")

    logger.info(f"📱 [微信] 获取用户信息成功 | unionid={data.get('unionid')}")

    return {
        "unionid": data.get("unionid"),
        "access_token": data.get("access_token"),
        "openid": data.get("openid"),
    }


async def _get_wechat_user_detail_real(code: str) -> dict:
    """真实微信API：获取用户详细信息（移动/公众号应用）"""
    # 第一步：获取 access_token
    basic_info = await _get_wechat_user_info_real(code)
    access_token = basic_info.get("access_token")
    unionid = basic_info.get("unionid")
    openid = basic_info.get("openid")

    if not access_token or not unionid:
        raise HTTPException(status_code=400, detail="获取微信授权信息失败")

    # 第二步：拉取用户信息
    url = "https://api.weixin.qq.com/sns/userinfo"
    params = {
        "access_token": access_token,
        "openid": openid,
        "lang": "zh_CN"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params)
            data = resp.json()
        except Exception as e:
            logger.error(f"[微信] 获取用户信息失败: {e}")
            raise HTTPException(status_code=500, detail=f"获取微信用户信息失败: {str(e)}")

    if "errcode" in data and data["errcode"] != 0:
        logger.error(f"[微信] 获取用户信息失败: {data}")
        raise HTTPException(status_code=400, detail=f"获取用户信息失败: {data.get('errmsg')}")

    logger.info(f"📱 [微信] 获取用户详情成功 | unionid={unionid}")

    return {
        "unionid": data.get("unionid"),
        "nickname": data.get("nickname"),
        "avatar_url": data.get("headimgurl"),
        "sex": data.get("sex"),  # 1=男, 2=女, 0=未知
        "province": data.get("province"),
        "city": data.get("city"),
        "country": data.get("country"),
        # 优先从用户详情获取 unionid，回退基础信息
        "unionid": data.get("unionid") or basic_info.get("unionid"),
    }


# ============== 微信网站应用扫码 ==============

async def _get_wechat_web_user_info(code: str) -> dict:
    """微信网站应用：获取 unionid/access_token 并拉取用户信息"""
    if not settings.WECHAT_WEB_ID or not settings.WECHAT_WEB_SECRET:
        raise HTTPException(status_code=500, detail="服务器未配置微信网站应用参数")

    # 1. 获取 access_token
    url = "https://api.weixin.qq.com/sns/oauth2/access_token"
    params = {
        "appid": settings.WECHAT_WEB_ID,
        "secret": settings.WECHAT_WEB_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params)
            data = resp.json()
        except Exception as e:
            logger.error(f"[微信WEB] API请求失败: {e}")
            raise HTTPException(status_code=500, detail=f"微信 API 请求失败: {str(e)}")

    if "errcode" in data and data["errcode"] != 0:
        logger.error(f"[微信WEB] 授权失败: {data}")
        raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg')}")

    access_token = data.get("access_token")
    unionid = data.get("unionid")
    openid = data.get("openid")

    # 2. 拉取用户信息
    user_info_url = "https://api.weixin.qq.com/sns/userinfo"
    user_info_params = {
        "access_token": access_token,
        "openid": openid,
        "lang": "zh_CN"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(user_info_url, params=user_info_params)
            user_info = resp.json()
        except Exception as e:
            logger.error(f"[微信WEB] 获取用户信息失败: {e}")
            # 如果获取用户信息失败，至少返回 unionid
            return {"unionid": unionid, "access_token": access_token}

    if "errcode" in user_info and user_info["errcode"] != 0:
        logger.error(f"[微信WEB] 获取用户信息失败: {user_info}")
        return {"unionid": unionid, "access_token": access_token}

    return {
        "unionid": user_info.get("unionid"),
        "nickname": user_info.get("nickname"),
        "avatar_url": user_info.get("headimgurl"),
        "sex": user_info.get("sex"),
        "province": user_info.get("province"),
        "city": user_info.get("city"),
        "country": user_info.get("country"),
        "unionid": user_info.get("unionid"),
        "access_token": access_token
    }


# ============== 统一接口 ==============

async def get_wechat_user_info(code: str) -> dict:
    """
    获取微信用户基础信息（unionid, access_token）

    强制使用真实微信API模式，并包含 unionid（若可用）
    """
    return await _get_wechat_user_info_real(code)


async def get_wechat_user_detail(code: str) -> dict:
    """
    获取微信用户详细信息（昵称、头像等）

    强制使用真实微信API模式，带 unionid
    """
    return await _get_wechat_user_detail_real(code)


# ============== 移动应用专用 ==============

async def get_wechat_user_info_app(code: str) -> dict:
    """强制使用 APP_ID/SECRET 获取完整用户信息（unionid 优先）"""
    return await _get_wechat_user_detail_real(code)


async def get_wechat_web_user_info(code: str) -> dict:
    """
    显式使用网站应用配置获取 unionid（扫码登录/绑定用）
    """
    return await _get_wechat_web_user_info(code)


# ============== 辅助函数 ==============

# ============== 网站扫码辅助函数 ==============
from urllib.parse import quote
import re

WEB_QR_TTL = 300
WEB_QR_READY_TTL = 60

def web_qr_key(mode: str, token: str) -> str:
    return f"wechat_web:{mode}:{token}"

def get_wechat_web_redirect_uri() -> str:
    # 优先使用 WECHAT_REDIRECT_URI，如果未配置则报错
    redirect = settings.WECHAT_REDIRECT_URI
    if not redirect:
        raise HTTPException(status_code=500, detail="未配置 WECHAT_REDIRECT_URI")

    # 确保 redirect_uri 是完整的 URL
    if not redirect.startswith("http"):
        redirect = f"https://{redirect}"

    # 拼接回调路径
    # 注意：这里要非常小心，避免重复拼接或拼错
    # 假设 settings.WECHAT_REDIRECT_URI 已经是完整的回调地址（如 https://example.com/auth/wechat_web/callback）
    # 或者只是域名（如 example.com）

    # 如果配置的已经是完整路径（包含 /auth/wechat_web/callback 或 /auth/wechat-web/callback），则直接使用
    if "/auth/wechat_web/callback" in redirect or "/auth/wechat-web/callback" in redirect:
        return redirect.rstrip('/')

    # 否则视为域名，默认拼接实际路由 /auth/wechat_web/callback
    return f"{redirect.rstrip('/')}/auth/wechat_web/callback"

def build_web_qr_url(mode: str, token: str) -> str:
    redirect = get_wechat_web_redirect_uri()
    # URL Encode 回调地址
    encoded_redirect = quote(redirect, safe="")

    state_prefix = settings.WECHAT_STATE_PREFIX or ""
    return (
        "https://open.weixin.qq.com/connect/qrconnect"
        f"?appid={settings.WECHAT_WEB_ID}"
        f"&redirect_uri={encoded_redirect}"
        f"&response_type=code"
        f"&scope=snsapi_login"
        f"&state={state_prefix}{mode}:{token}#wechat_redirect"
    )

async def extract_qr_image(url: str) -> str | None:
    """从微信授权页提取二维码图片地址"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0)
            if resp.status_code == 200:
                # 寻找 src="/connect/qrcode/..."
                match = re.search(r'src="(/connect/qrcode/[^"]+)"', resp.text)
                if match:
                    return f"https://open.weixin.qq.com{match.group(1)}"
    except Exception as e:
        logger.warning(f"Failed to extract QR image: {e}")
    return None
