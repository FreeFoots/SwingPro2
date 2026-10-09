import json
from redis.asyncio import Redis

ACTIVE_PLAYER_TTL = 24 * 3600  # 24h


def _user_active_key(user_id: str) -> str:
    return f"user:active_player:{user_id}"

async def set_user_active_player(r: Redis, user_id: str, data: dict, ttl: int = ACTIVE_PLAYER_TTL):
    await r.set(_user_active_key(user_id), json.dumps(data), ex=ttl)


async def get_user_active_player(r: Redis, user_id: str) -> dict | None:
    val = await r.get(_user_active_key(user_id))
    if not val:
        return None
    try:
        return json.loads(val)
    except Exception:
        return None
