from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError, ExpiredSignatureError
from jose.exceptions import JWTClaimsError
from app.core.config import settings
import secrets, hashlib

# =========================
# 统一使用北京时间 (+8)
# =========================
BEIJING_TZ = timezone(timedelta(hours=8))

def now_bj() -> datetime:
    """返回当前北京时间"""
    return datetime.now(BEIJING_TZ)

# =========================
# Access Token 生成
# =========================
def create_access_token(sub: str, role: str, sid: str, client_type: str):
    """生成 Access Token（JWT）"""
    iat = now_bj()
    exp = iat + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": sub,
        "role": role,
        "sid": sid,
        "client": client_type,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": "swingpro2.platform",
        "aud": "swingpro2.app",
        "typ": "access",
        "ver": 1
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

# =========================
# Refresh Token 生成（不透明）
# =========================
def gen_refresh_token_pair():
    """
    生成 Refresh Token：
    <token_id>.<secret>
    数据库存哈希(secret_hash)
    """
    token_id = secrets.token_hex(16)
    secret = secrets.token_hex(16)
    rt_plain = f"{token_id}.{secret}"
    rt_hash = hashlib.sha256(secret.encode()).hexdigest()
    return token_id, secret, rt_plain, rt_hash


# =========================
# Access Token 校验
# =========================
class TokenDecodeError(Exception):
    """Access Token 解码失败"""


class TokenExpiredError(TokenDecodeError):
    """Access Token 过期"""


def decode_access_token(token: str) -> dict:
    """
    解码并校验 Access Token。
    - 验证签名 / 过期时间
    - 校验 issuer / audience / typ
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience="swingpro2.app",
            issuer="swingpro2.platform",
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("access token expired") from exc
    except (JWTClaimsError, JWTError) as exc:
        raise TokenDecodeError("failed to decode access token") from exc

    if payload.get("typ") != "access":
        raise TokenDecodeError("invalid token type")

    return payload
