"""短信验证码登录服务。

生产环境应在 send_login_code 中对接真实短信通道。
DEBUG 下使用固定验证码，方便本地小程序联调。
"""

import logging
import re
import secrets

from fastapi import HTTPException

from app.core.config import settings
from app.core.redis_client import RedisKeys, get_redis

logger = logging.getLogger(__name__)

PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


class SmsService:
    @staticmethod
    def normalize_phone(phone: str) -> str:
        normalized = (phone or "").strip()
        if not PHONE_PATTERN.match(normalized):
            raise HTTPException(status_code=400, detail="请输入正确的 11 位手机号")
        return normalized

    @staticmethod
    def _generate_code() -> str:
        debug_code = (settings.SMS_DEBUG_CODE or "").strip()
        if debug_code:
            return debug_code
        if settings.DEBUG:
            return "123456"
        return f"{secrets.randbelow(1000000):06d}"

    @staticmethod
    async def send_login_code(phone: str) -> dict:
        phone = SmsService.normalize_phone(phone)
        try:
            redis = get_redis()
        except RuntimeError as exc:
            logger.error("发送验证码失败：Redis 未初始化")
            raise HTTPException(status_code=503, detail="验证码服务暂不可用") from exc

        limit_key = RedisKeys.SMS_SEND_LIMIT.format(phone=phone)
        if await redis.exists(limit_key):
            raise HTTPException(status_code=429, detail="验证码发送过于频繁，请稍后再试")

        code = SmsService._generate_code()
        await redis.setex(
            RedisKeys.SMS_LOGIN_CODE.format(phone=phone),
            settings.SMS_CODE_TTL_SECONDS,
            code,
        )
        await redis.setex(limit_key, settings.SMS_SEND_INTERVAL_SECONDS, "1")

        logger.info("短信验证码已生成: phone=%s expire=%ss", phone, settings.SMS_CODE_TTL_SECONDS)

        result = {
            "phone": phone,
            "expire_in": settings.SMS_CODE_TTL_SECONDS,
            "resend_in": settings.SMS_SEND_INTERVAL_SECONDS,
        }
        if settings.DEBUG:
            result["debug_code"] = code
        return result

    @staticmethod
    async def verify_login_code(phone: str, sms_code: str) -> str:
        phone = SmsService.normalize_phone(phone)
        token = (sms_code or "").strip()
        if not re.fullmatch(r"\d{4,8}", token):
            raise HTTPException(status_code=400, detail="请输入正确的验证码")

        try:
            redis = get_redis()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="验证码服务暂不可用") from exc

        key = RedisKeys.SMS_LOGIN_CODE.format(phone=phone)
        stored = await redis.get(key)
        if not stored or stored != token:
            raise HTTPException(status_code=401, detail="验证码错误或已过期")

        await redis.delete(key)
        return phone
