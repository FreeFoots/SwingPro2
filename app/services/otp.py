import random, string, time
import httpx
from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_mem_code: dict[str, str] = {}
_mem_cd: dict[str, float] = {}
_mem_cnt: dict[str, int] = {}

def gen_otp() -> str:
    return "".join(random.choices(string.digits, k=6))

def _now() -> float:
    return time.time()

def _todaykey(tel: str) -> str:
    return f"{tel}:{time.strftime('%Y%m%d')}"


async def send_sms(tel: str, otp: str) -> bool:
    """
    发送短信验证码 - 支持三种模式

    SMS_PROVIDER 配置:
    - local: 本地测试模式，在终端打印验证码
    - spug: 使用 Spug Push 发送真实短信
    - aliyun: 使用阿里云短信服务发送真实短信
    """
    provider = settings.SMS_PROVIDER.lower()

    if provider == "local":
        return await _send_sms_local(tel, otp)
    elif provider == "spug":
        return await _send_sms_spug(tel, otp)
    elif provider == "aliyun":
        return await _send_sms_aliyun(tel, otp)
    else:
        logger.error(f"Unknown SMS provider: {provider}")
        return False


async def _send_sms_local(tel: str, otp: str) -> bool:
    """本地测试模式：在终端打印验证码"""
    logger.info("Local SMS development mode; code is printed to the terminal")
    print(f"\n{'='*60}")
    print(f"📱 短信验证码 (本地测试模式)")
    print(f"{'='*60}")
    print(f"手机号: {tel}")
    print(f"验证码: {otp}")
    print(f"有效期: {settings.OTP_TTL_SECONDS}秒")
    print(f"{'='*60}\n")
    return True


async def _send_sms_spug(tel: str, otp: str) -> bool:
    """Spug Push 模式：通过 Spug 发送真实短信"""
    if not settings.SMS_SPUG_URL:
        logger.error("SMS_PROVIDER=spug but SMS_SPUG_URL not set")
        return False

    try:
        body = {
            "name": settings.APP_NAME,
            "code": otp,
            "targets": tel
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.SMS_SPUG_URL, json=body)
            if resp.status_code == 200:
                logger.info("SMS sent via Spug")
                return True
            else:
                logger.error(f"[Spug] SMS send failed: {resp.status_code} {resp.text}")
                return False
    except Exception as e:
        logger.error(f"[Spug] SMS send exception: {e}")
        return False


async def _send_sms_aliyun(tel: str, otp: str) -> bool:
    """阿里云短信模式：使用阿里云短信服务"""
    if not settings.SMS_ALIYUN_ACCESS_KEY_ID or not settings.SMS_ALIYUN_ACCESS_KEY_SECRET:
        logger.error("SMS_PROVIDER=aliyun but credentials not set")
        return False

    try:
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
        from alibabacloud_tea_util import models as util_models

        # 创建客户端配置
        config = open_api_models.Config(
            access_key_id=settings.SMS_ALIYUN_ACCESS_KEY_ID,
            access_key_secret=settings.SMS_ALIYUN_ACCESS_KEY_SECRET,
            endpoint='dysmsapi.aliyuncs.com'
        )

        # 创建客户端
        client = DysmsapiClient(config)

        # 构建请求
        request = dysmsapi_models.SendSmsRequest(
            phone_numbers=tel,
            sign_name=settings.SMS_ALIYUN_SIGN_NAME,
            template_code=settings.SMS_ALIYUN_TEMPLATE_CODE,
            template_param=f'{{"code":"{otp}"}}'
        )

        # 发送请求
        runtime = util_models.RuntimeOptions()
        response = client.send_sms_with_options(request, runtime)

        # 检查结果
        if response.body.code == 'OK':
            logger.info("SMS sent via Aliyun")
            return True
        else:
            logger.error(f"[阿里云] SMS send failed: {response.body.code} {response.body.message}")
            return False

    except Exception as e:
        logger.error(f"[阿里云] SMS send exception: {e}")
        return False

async def can_send_otp(r, tel: str) -> bool:
    if r:
        if await r.exists(f"otp:cd:{tel}"):
            return False
        cnt = int(await r.get(f"otp:cnt:{_todaykey(tel)}") or 0)
        return cnt < settings.OTP_DAILY_LIMIT
    if tel in _mem_cd and _now() - _mem_cd[tel] < settings.OTP_SEND_COOLDOWN_SECONDS:
        return False
    return _mem_cnt.get(_todaykey(tel), 0) < settings.OTP_DAILY_LIMIT

async def save_otp(r, tel: str, otp: str):
    if r:
        await r.setex(f"otp:code:{tel}", settings.OTP_TTL_SECONDS, otp)
        await r.setex(f"otp:cd:{tel}", settings.OTP_SEND_COOLDOWN_SECONDS, "1")
        key = f"otp:cnt:{_todaykey(tel)}"
        await r.incr(key); await r.expire(key, 86400)
        return
    _mem_code[tel] = otp; _mem_cd[tel] = _now()
    _mem_cnt[_todaykey(tel)] = _mem_cnt.get(_todaykey(tel), 0) + 1

async def verify_otp(r, tel: str, otp: str) -> bool:
    if r:
        val = await r.get(f"otp:code:{tel}")
        if not val or val != otp:
            return False
        await r.delete(f"otp:code:{tel}")
        await r.delete(f"otp:cd:{tel}")
        return True
    val = _mem_code.get(tel)
    ok = (val == otp)
    if ok:
        _mem_code.pop(tel, None)
        _mem_cd.pop(tel, None)
    return ok


async def check_otp(r, tel: str, otp: str) -> bool:
    if r:
        val = await r.get(f"otp:code:{tel}")
        return bool(val and val == otp)
    val = _mem_code.get(tel)
    return bool(val and val == otp)


async def consume_otp(r, tel: str, otp: str) -> bool:
    if r:
        val = await r.get(f"otp:code:{tel}")
        if not val or val != otp:
            return False
        await r.delete(f"otp:code:{tel}")
        await r.delete(f"otp:cd:{tel}")
        return True
    val = _mem_code.get(tel)
    if val != otp:
        return False
    _mem_code.pop(tel, None)
    _mem_cd.pop(tel, None)
    return True
