"""Separate, intent-bound order preparation credentials; never exposed to the model or SQLite."""
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from .errors import AppError
from .tools import DraftIntent, money


@dataclass
class OrderCapability:
    user: str
    items: list
    request_key: str
    expires_at: int
    token: str = field(repr=False)


def draft_snapshot(raw):
    if not isinstance(raw, dict) or raw.get("paid") is not False or raw.get("currency") != "CNY":
        raise ValueError()
    did, status, version = raw.get("draftId"), raw.get("status"), raw.get("version")
    if not isinstance(did, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", did):
        raise ValueError()
    if status not in ("PREPARED", "CONFIRMED", "CANCELLED", "EXPIRED") or type(version) is not int or version < 1:
        raise ValueError()
    expires = raw.get("expiresAt")
    if type(expires) is not int or expires < 0:
        raise ValueError()
    items = raw.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError()
    clean = []
    seen = set()
    for item in items:
        parsed = DraftIntent.model_validate({"items": [{"medicineId": item["medicineId"], "quantity": item["quantity"]}]})
        name = item["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or item["medicineId"] in seen:
            raise ValueError()
        seen.add(item["medicineId"])
        clean.append({**parsed.model_dump()["items"][0], "name": name, "price": money(item["price"])})
    return {"draftId": did, "status": status, "version": version, "totalPrice": money(raw["totalPrice"]),
            "expiresAt": expires, "currency": "CNY", "paid": False, "items": clean}


class OrderPreparation:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    def headers(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AppError(401, "ORDER_AUTHORIZATION_INVALID", "订单准备授权无效，请重新授权")
        return {"Authorization": "Bearer " + token, "X-AI-Service-Key": self.settings.service_key}

    async def capability(self, token, user, intent):
        try:
            async with self.client.stream(
                "GET", self.settings.java_base_url + "/internal/ai/v1/order-preparation",
                headers=self.headers(token), timeout=5,
            ) as response:
                if response.status_code in (401, 403):
                    raise AppError(401, "ORDER_AUTHORIZATION_INVALID", "订单准备授权已失效或撤销")
                if response.status_code != 200:
                    raise AppError(503, "ORDER_AUTHORIZATION_UNAVAILABLE", "订单准备授权服务不可用")
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 8192:
                        raise ValueError()
            raw = json.loads(body)
            items = DraftIntent.model_validate({"items": raw["items"]}).model_dump()["items"]
            if (raw.get("scope") != "AGENT_ORDER_PREPARE" or raw.get("userId") != user
                    or items != intent or type(raw.get("expiresAt")) is not int
                    or raw["expiresAt"] <= time.time() or not isinstance(raw.get("requestKey"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw["requestKey"])):
                raise ValueError()
            return OrderCapability(user, items, raw["requestKey"], raw["expiresAt"], token)
        except httpx.HTTPError:
            raise AppError(503, "ORDER_AUTHORIZATION_UNAVAILABLE", "订单准备授权服务暂时不可用") from None
        except (ValueError, KeyError, TypeError):
            raise AppError(403, "ORDER_INTENT_MISMATCH", "订单准备授权与当前用户或商品数量不符") from None

    async def check(self, capability):
        current = await self.capability(capability.token, capability.user, capability.items)
        if current.request_key != capability.request_key or current.expires_at != capability.expires_at:
            raise AppError(409, "ORDER_AUTHORIZATION_CHANGED", "订单准备授权已变化")

    async def prepare(self, capability, args, call_id):
        if args["items"] != capability.items:
            raise AppError(403, "ORDER_INTENT_MISMATCH", "模型请求的商品或数量超出用户授权")
        headers = {**self.headers(capability.token), "Idempotency-Key": capability.request_key, "X-Request-ID": call_id}
        # Never automatically retry a write. A lost response is resolved in the USER draft list.
        try:
            async with self.client.stream(
                "POST", self.settings.java_base_url + "/internal/ai/v1/order-drafts",
                headers=headers, json=args, timeout=10,
            ) as response:
                if response.status_code in (401, 403):
                    raise AppError(401, "ORDER_AUTHORIZATION_INVALID", "订单准备授权已失效或撤销")
                if response.status_code not in (200, 400, 409):
                    return self.uncertain()
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 16384:
                        return self.uncertain()
                raw = json.loads(body)
                if not isinstance(raw, dict):
                    return self.uncertain()
                if response.status_code != 200:
                    messages = {"SALE_NOT_ALLOWED": "商品销售资格不满足，无法准备草稿",
                                "OUT_OF_STOCK": "商品库存不足", "INTENT_MISMATCH": "商品与用户授权不符",
                                "IDEMPOTENCY_CONFLICT": "订单准备请求冲突"}
                    code = raw.get("code")
                    return {"ok": False, "code": code if code in messages else "DRAFT_PREPARE_FAILED",
                            "message": messages.get(code, "草稿准备失败，请核对商品或稍后重试")}
                snapshot = draft_snapshot(raw)
                actual = sorted([{"medicineId": item["medicineId"], "quantity": item["quantity"]}
                                 for item in snapshot["items"]], key=lambda item: item["medicineId"])
                if actual != capability.items:
                    return self.uncertain()
                return {"ok": True, "draft": snapshot}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return self.uncertain()

    @staticmethod
    def uncertain():
        return {"ok": False, "code": "DRAFT_OUTCOME_UNKNOWN",
                "message": "草稿结果尚不确定，请到我的草稿核对；本次请求不会自动重试，不代表已付款"}

