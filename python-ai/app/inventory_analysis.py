"""Validate model judgments against a single page of live catalog data."""


def analyze_inventory(args, page):
    if page is None:
        return failure("请先读取同一游标的实时库存，查询目的使用 match")
    judgments = {item["medicineId"]: item for item in args["items"]}
    rows = page["products"]
    if len(judgments) != len(args["items"]) or set(judgments) != {row["id"] for row in rows}:
        return failure("结构化结果必须逐项覆盖本页商品，商品 ID 不能重复或超出本页")

    items = []
    for row in rows:
        items.append({
            "medicineId": row["id"], "name": row["name"], "stock": row["stock"],
            "price": row["price"], "currency": row["currency"], "draftEligible": row["draftEligible"],
            "matchesNeed": judgments[row["id"]]["matchesNeed"],
        })
    return {"ok": True, "analysis": {
        "afterId": page["afterId"], "nextAfterId": page["nextAfterId"],
        "queriedAt": page["queriedAt"], "items": items,
    }}


def failure(message):
    return {"ok": False, "code": "INVENTORY_ANALYSIS_INVALID", "message": message}
