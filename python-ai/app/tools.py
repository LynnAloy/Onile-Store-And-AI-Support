"""Read-only tool registry. No model-selected URLs, credentials or business writes."""
import asyncio
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, model_validator

from .errors import AppError


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Search(Arguments):
    name: str = Field(min_length=1, max_length=100)
    limit: StrictInt = Field(default=5, ge=1, le=10)


class Detail(Arguments):
    medicineId: StrictInt = Field(ge=1, le=2147483647)


class CatalogPage(Arguments):
    afterId: StrictInt = Field(default=0, ge=0, le=2147483647)
    purpose: Literal["list", "match"] = "list"


class InventoryJudgment(Detail):
    matchesNeed: StrictBool


class InventoryAnalysis(Arguments):
    afterId: StrictInt = Field(default=0, ge=0, le=2147483647)
    items: list[InventoryJudgment] = Field(max_length=20)


class Order(Arguments):
    orderId: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class DraftItem(Arguments):
    medicineId: StrictInt = Field(ge=1, le=2147483647)
    quantity: StrictInt = Field(ge=1, le=99)


class DraftIntent(Arguments):
    items: list[DraftItem] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.medicineId for item in self.items}) != len(self.items):
            raise ValueError("Duplicate product")
        self.items.sort(key=lambda item: item.medicineId)
        return self


class PurchaseLine(Arguments):
    medicineId: StrictInt = Field(ge=1, le=2147483647)
    quantity: StrictInt | None = Field(default=None, ge=1, le=99)
    evidence: str | None = Field(default=None, min_length=1, max_length=120)


class PurchaseProposal(Arguments):
    items: list[PurchaseLine] = Field(min_length=1, max_length=10)


REGISTRY = {
    "list_inventory": (CatalogPage, "Read a page of live inventory. For plain inventory listing use purpose=list; for matching products to a health request use purpose=match, then submit analyze_inventory for that page."),
    "analyze_inventory": (InventoryAnalysis, "Submit a boolean matchesNeed for every product ID in the specified purpose=match inventory page. Use your knowledge of the named medicine's general use and the user's request. Do not require catalog review records. This tool does not place orders."),
    "propose_purchase": (PurchaseProposal, "Build a READ-ONLY purchase checklist from products already returned by catalog tools. Preserve each requested quantity even if a product is not eligible. Optional evidence quotes the current user message verbatim; the server independently validates quantity against that message. Use null when quantity is missing. Never creates a draft or grants permission."),
    "prepare_order_draft": (DraftIntent, "Prepare an UNPAID order draft ONLY for the exact user-authorized product IDs and quantities in authorizedOrderItems. Does not confirm, pay or reserve stock."),
    "search_medicines": (Search, "Search the real medicine catalog by a user-specified product name, returning current prices and stock. Not a medical recommendation."),
    "get_medicine": (Detail, "Get real product details by medicineId. Does not determine medical suitability."),
    "get_my_order": (Order, "Get the current user's existing order summary by orderId. Never returns recipient or payment credentials."),
}
TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": name, "description": description, "parameters": model.model_json_schema(),
}} for name, (model, description) in REGISTRY.items() if name != "prepare_order_draft"]


def tool_schemas(order_authorized=False):
    if not order_authorized:
        return TOOL_SCHEMAS
    model, description = REGISTRY["prepare_order_draft"]
    reads = [tool for tool in TOOL_SCHEMAS if tool["function"]["name"] != "propose_purchase"]
    return [*reads, {"type": "function", "function": {
        "name": "prepare_order_draft", "description": description, "parameters": model.model_json_schema()}}]


def validated_call(call):
    try:
        if not isinstance(call, dict) or call.get("type", "function") != "function":
            raise ValueError()
        function = call["function"]
        if not isinstance(function, dict) or set(function) - {"name", "arguments", "index"}:
            raise ValueError()
        name = function["name"]
        if not isinstance(name, str) or name not in REGISTRY:
            raise ValueError()
        raw = function["arguments"]
        if not isinstance(raw, dict) or len(json.dumps(raw, ensure_ascii=False)) > 2048:
            raise ValueError()
        args = REGISTRY[name][0].model_validate(raw).model_dump()
        return name, args
    except (KeyError, TypeError, ValueError, ValidationError):
        raise AppError(502, "INVALID_TOOL_CALL", "模型请求了无效工具或参数，本次查询已停止") from None


def money(value):
    if isinstance(value, bool):
        raise ValueError()
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal("9999999999.99"):
            raise ValueError()
        if result != result.quantize(Decimal(".01")):
            raise ValueError()
        return format(result, ".2f")
    except (InvalidOperation, TypeError):
        raise ValueError() from None


def product(raw):
    if not isinstance(raw, dict) or type(raw.get("id")) is not int or raw["id"] < 1:
        raise ValueError()
    name, stock = raw.get("name"), raw.get("stock")
    if not isinstance(name, str) or not 1 <= len(name) <= 200 or type(stock) is not int or stock < 0:
        raise ValueError()
    result = {"id": raw["id"], "name": name, "price": money(raw.get("price")), "stock": stock, "currency": "CNY"}
    result["draftEligible"] = raw.get("draftEligible") is True
    result["draftBlockedReason"] = raw.get("draftBlockedReason", "商品资格待核验")
    evidence = raw.get("medicalEvidence")
    if isinstance(evidence, dict) and evidence.get("status") == "APPROVED":
        if (type(evidence.get("version")) is int and evidence["version"] > 0
                and isinstance(evidence.get("categories"), list)
                and all(isinstance(value, str) and 0 < len(value) <= 50 for value in evidence["categories"])
                and isinstance(evidence.get("indications"), str) and len(evidence["indications"]) <= 2000
                and isinstance(evidence.get("source"), str) and len(evidence["source"]) <= 500):
            result["medicalEvidence"] = {key: evidence[key] for key in ("version", "categories", "indications", "source")}
            limit=evidence.get("maxUnitsPerOrder")
            if type(limit) is int and 1 <= limit <= 99:
                result["medicalEvidence"]["maxUnitsPerOrder"]=limit
    if not isinstance(result["draftBlockedReason"], str) or len(result["draftBlockedReason"]) > 200:
        raise ValueError()
    return result


def order_summary(raw):
    if not isinstance(raw, dict):
        raise ValueError()
    oid, status, items = raw.get("orderId"), raw.get("status"), raw.get("items")
    if not isinstance(oid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", oid):
        raise ValueError()
    if not isinstance(status, str) or not 1 <= len(status) <= 40 or not isinstance(items, list) or len(items) > 50:
        raise ValueError()
    clean = []
    for item in items:
        if not isinstance(item, dict) or type(item.get("medicineId")) is not int or item["medicineId"] < 1:
            raise ValueError()
        if type(item.get("quantity")) is not int or not 1 <= item["quantity"] <= 100000:
            raise ValueError()
        name = item.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > 200):
            raise ValueError()
        clean.append({"medicineId": item["medicineId"], "name": name or "商品",
                      "quantity": item["quantity"], "price": money(item.get("price"))})
    return {"orderId": oid, "status": status, "totalPrice": money(raw.get("totalPrice")),
            "currency": "CNY", "items": clean}


class ReadTools:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def execute(self, name, args, token, trace_id):
        name, args = validated_call({"function": {"name": name, "arguments": args}})
        if name in ("prepare_order_draft", "propose_purchase", "analyze_inventory"):
            raise AppError(403, "ORDER_AUTHORIZATION_REQUIRED", "订单准备需要独立的指定商品授权")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AppError(401, "UNAUTHORIZED", "AI授权无效")
        if name == "search_medicines":
            path, params = "medicines", args
        elif name == "list_inventory":
            path, params = "catalog", {"afterId": args["afterId"]}
        elif name == "get_medicine":
            path, params = "medicines/" + str(args["medicineId"]), None
        else:
            path, params = "orders/" + quote(args["orderId"], safe=""), None
        result = {"ok": False}
        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET", self.settings.java_base_url + "/internal/ai/v1/" + path, params=params,
                    headers={"Authorization": "Bearer " + token, "X-AI-Service-Key": self.settings.service_key,
                             "X-Request-ID": trace_id}, timeout=5,
                ) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise AppError(401, "UNAUTHORIZED", "AI授权已失效，请重新授权")
                    if status == 404:
                        result = {"ok": False, "code": "NOT_FOUND", "message": "未找到商品或本人订单"}
                        break
                    if status in (429, 502, 503, 504) and attempt == 0:
                        await asyncio.sleep(.1)
                        continue
                    if status != 200:
                        result = {"ok": False, "code": "JAVA_UNAVAILABLE", "message": "业务查询暂时不可用"}
                        break
                    body = bytearray()
                    response_limit = 524288 if name == "list_inventory" else 32768
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > response_limit:
                            raise ValueError()
                    raw = json.loads(body, parse_float=Decimal)
                    if name == "search_medicines":
                        if not isinstance(raw, list) or len(raw) > args["limit"]:
                            raise ValueError()
                        data = {"products": [product(item) for item in raw]}
                    elif name == "list_inventory":
                        if not isinstance(raw, list) or len(raw) > 20:
                            raise ValueError()
                        rows = [product(item) for item in raw]
                        ids = [row["id"] for row in rows]
                        if ids != sorted(set(ids)) or any(pid <= args["afterId"] for pid in ids):
                            raise ValueError()
                        for row in rows:
                            if "medicalEvidence" in row:
                                row["medicalEvidence"].pop("indications")
                        data = {"products": rows, "catalogListing": True, "catalogCount": len(rows),
                                "afterId": args["afterId"], "purpose": args["purpose"],
                                "nextAfterId": ids[-1] if len(ids) == 20 else None}
                    elif name == "get_medicine":
                        data = {"products": [product(raw)]}
                        if data["products"][0]["id"] != args["medicineId"]:
                            raise ValueError()
                    else:
                        data = {"order": order_summary(raw)}
                        if data["order"]["orderId"] != args["orderId"]:
                            raise ValueError()
                    result = {"ok": True, **data}
                    break
            except httpx.HTTPError:
                if attempt == 0:
                    await asyncio.sleep(.1)
                    continue
                result = {"ok": False, "code": "JAVA_UNAVAILABLE", "message": "业务查询超时或网络不可用"}
            except (ValueError, TypeError, KeyError):
                result = {"ok": False, "code": "TOOL_RESULT_INVALID", "message": "业务数据格式异常，未使用该结果"}
                break
        result["queriedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        result["snapshot"] = True
        if len(json.dumps(result, ensure_ascii=False)) > (32000 if name == "list_inventory" else 6000):
            return {"ok": False, "code": "TOOL_RESULT_LIMIT", "message": "查询结果过长，请缩小查询范围"}
        return result


def argument_summary(name, args):
    if name == "list_inventory":
        return args
    if name == "analyze_inventory":
        return {"afterId": args["afterId"], "count": len(args["items"])}
    if name == "propose_purchase":
        return {"items": [{"medicineId": item["medicineId"], "quantity": item["quantity"]} for item in args["items"]]}
    if name == "prepare_order_draft":
        return {"items": args["items"]}
    if name == "search_medicines":
        return {"keywordLength": len(args["name"]), "limit": args["limit"]}
    if name == "get_medicine":
        return {"medicineId": args["medicineId"]}
    return {"orderIdSuffix": args["orderId"][-6:]}

