"""微信小程序登录：用 wx.login code 换 openid。AppSecret 只在服务端使用。"""

import logging
from typing import Optional

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"


class WeChatAuthService:
    @staticmethod
    async def exchange_code(js_code: str, appid: Optional[str] = None) -> dict:
        code = (js_code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="缺少微信登录凭证")

        configured_appid = (settings.WECHAT_MINI_APPID or "").strip()
        secret = (settings.WECHAT_MINI_SECRET or "").strip()
        if not configured_appid or not secret:
            raise HTTPException(status_code=503, detail="未配置微信小程序登录，请联系管理员")

        runtime_appid = (appid or "").strip()
        if runtime_appid and runtime_appid != configured_appid:
            raise HTTPException(status_code=400, detail="小程序 appid 不匹配")

        params = {
            "appid": configured_appid,
            "secret": secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(JSCODE2SESSION_URL, params=params)
                payload = response.json()
        except Exception as exc:
            logger.error("调用微信 jscode2session 失败: %s", exc)
            raise HTTPException(status_code=502, detail="微信登录服务暂时不可用") from exc

        errcode = payload.get("errcode") or 0
        if errcode:
            logger.warning("微信登录换票失败: errcode=%s", errcode)
            raise HTTPException(status_code=401, detail="微信登录失败，请重试")

        openid = payload.get("openid")
        if not openid:
            raise HTTPException(status_code=401, detail="微信登录失败，请重试")

        return {
            "openid": openid,
            "unionid": payload.get("unionid") or None,
        }
