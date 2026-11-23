import math
import re

import httpx

from .errors import AppError


HEALTH_KEYS = {"age", "gender", "heightCm", "weightKg", "bmi", "medicalHistory",
               "medicalHistoryText", "allergiesText", "medicationsText", "lifestyleText", "healthNotes"}


class JavaIdentity:
    def __init__(self, client, settings):
        self.client = client
        self.settings = settings

    async def get(self, path, token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AppError(401, "UNAUTHORIZED", "请重新获取AI会话授权")
        try:
            response = await self.client.get(
                self.settings.java_base_url + "/internal/ai/v1/" + path,
                headers={"Authorization": "Bearer " + token,
                         "X-AI-Service-Key": self.settings.service_key},
                timeout=5,
            )
        except httpx.HTTPError:
            raise AppError(503, "IDENTITY_UNAVAILABLE", "身份服务暂时不可用") from None
        if response.status_code in (401, 403):
            raise AppError(401, "UNAUTHORIZED", "AI授权已失效，请重新授权")
        if response.status_code != 200:
            raise AppError(503, "IDENTITY_UNAVAILABLE", "身份服务暂时不可用")
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, TypeError):
            raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "身份服务响应格式异常") from None

    async def resolve(self, token):
        data = await self.get("me", token)
        username, scope = data.get("userId"), data.get("scope")
        if scope != "AGENT_READ" or not isinstance(username, str) or not username:
            raise AppError(401, "UNAUTHORIZED", "AI授权范围不正确")
        return username

    async def personalization(self, token, details=False):
        path = "personalization-context" if details else "personalization-status"
        data = await self.get(path, token)
        enabled, revision = data.get("enabled"), data.get("revision")
        if not isinstance(enabled, bool) or type(revision) is not int or revision < 0:
            raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "个性化授权响应格式异常")
        result = {"enabled": enabled, "revision": revision}
        if not enabled or not details:
            return result
        raw = data.get("profile")
        if not isinstance(raw, dict):
            raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "健康资料响应格式异常")
        profile = {}
        for key in HEALTH_KEYS & raw.keys():
            value = raw[key]
            if key in {"age", "heightCm", "weightKg", "bmi"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "健康数值响应格式异常")
            elif key == "medicalHistory":
                if not isinstance(value, list) or len(value) > 30 or any(
                    not isinstance(item, str) or len(item) > 100 for item in value
                ):
                    raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "病史响应格式异常")
            elif not isinstance(value, str) or len(value) > 2000:
                raise AppError(502, "IDENTITY_PROTOCOL_ERROR", "健康描述响应格式异常")
            profile[key] = value
        result["profile"] = profile
        return result
