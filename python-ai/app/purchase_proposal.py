"""Ground model-proposed quantities in literal user text and real catalog hits; no writes."""
import re


UNITS = r"(?:件|盒|瓶|袋|包|支|罐|份|个)"
DIGITS = "零一二三四五六七八九"


def is_purchase_request(message):
    if re.search(r"(?:只查询|仅查询|不要购买|不购买|不想买|不要下单|不下单)", message):
        return False
    return bool(re.search(r"(?:购买|下单|订购|想买|帮我买)", message))


def number_texts(quantity):
    if quantity < 10:
        chinese = DIGITS[quantity]
    else:
        tens, ones = divmod(quantity, 10)
        chinese = (DIGITS[tens] if tens > 1 else "") + "十" + (DIGITS[ones] if ones else "")
    return [str(quantity), chinese, *(["两"] if quantity == 2 else [])]


def literal_quantity(span, term, quantity):
    number = "(?:" + "|".join(re.escape(value) for value in number_texts(quantity)) + ")"
    product = re.escape(term)
    before = r"(?<![0-9一二三四五六七八九十两])" + number + r"\s*" + UNITS + r"\s*(?:的\s*)?" + product
    after = product + r"\s*(?:(?:买|要|购买|订购|下单)\s*)?" + number + r"\s*" + UNITS
    marked = product + r"\s*(?:[xX×*]|数量\s*[:：]?)\s*" + number + r"(?![0-9一二三四五六七八九十])"
    return any(re.search(pattern, span, re.IGNORECASE) for pattern in (before, after, marked))


def propose_purchase(args, message, products, search_terms):
    items, seen = [], set()
    for requested in args["items"]:
        pid, quantity = requested["medicineId"], requested["quantity"]
        span = requested.get("evidence") or message
        if pid not in products or pid in seen or span not in message:
            return invalid("清单必须引用本轮实际查询的商品和当前消息原文")
        seen.add(pid)
        product = products[pid]
        # A truncated keyword such as “虚构” must not stand in for “虚构待审核”.
        terms = [term for term, ids in search_terms.items() if pid in ids
                 and re.search(re.escape(term) + r"(?![\w\u4e00-\u9fff])", span)]
        if product["name"] in span:
            terms.append(product["name"])
        id_pattern = r"(?:商品\s*ID|ID|编号)\s*[:：]?\s*" + str(pid) + r"(?![0-9])"
        explicit_id = re.search(id_pattern, span, re.IGNORECASE)
        if explicit_id:
            terms.append(explicit_id.group())
        if not terms:
            return invalid("商品名称或ID无法与当前消息的购买要求对应，请明确规格")
        if quantity is None:
            explicit = {value for value in range(1, 100)
                        if any(text in message for text in number_texts(value))
                        and any(literal_quantity(message, term, value) for term in terms)}
            if len(explicit) == 1:
                quantity = explicit.pop()
            elif len(explicit) > 1:
                return invalid("同一商品出现多个数量，请明确本次数量")
        if quantity is not None and not any(literal_quantity(span, term, quantity) for term in terms):
            if requested["quantity"] is not None:
                return invalid("数量必须与当前消息中该商品的明确数量一致，不能猜测或交换")
        # A broad catalog keyword may match several variants. Do not silently pick a formulation.
        ambiguous = not explicit_id and any(len(ids) > 1 for term, ids in search_terms.items()
                                            if term in terms and pid in ids)
        items.append({**product, "quantity": quantity,
                      "quantitySource": "explicit" if quantity is not None else "missing",
                      "autoSelect": not ambiguous,
                      "selectionNote": "匹配多个商品规格，请先核对并选择" if ambiguous else ""})
    return {"ok": True, "proposal": {"items": items, "requiresUserAuthorization": True, "snapshot": True}}


def invalid(message):
    return {"ok": False, "code": "PURCHASE_PROPOSAL_INVALID", "message": message}


def proposal_reply(proposal):
    lines = [item["name"] + " ×" + (str(item["quantity"]) if item["quantity"] is not None else "待填写数量")
             for item in proposal["items"]]
    blocked = []
    for item in proposal["items"]:
        if not item["draftEligible"]:
            blocked.append(item["name"] + "：" + item["draftBlockedReason"])
        elif item["quantity"] is not None and item["quantity"] > item["stock"]:
            blocked.append(item["name"] + "：库存不足")
        if not item["autoSelect"]:
            blocked.append(item["name"] + "：请先确认具体商品规格")
    text = "已识别待核对购买清单：" + "；".join(lines) + "。清单未授权、未下单。"
    return text + ("暂不能准备草稿：" + "；".join(blocked) + "。" if blocked else "请核对商品和数量后再授权准备草稿。")


def ambiguous_catalog_reply(message, products, search_terms):
    for term, ids in search_terms.items():
        if len(ids) < 2 or not re.search(re.escape(term) + r"(?![\w\u4e00-\u9fff])", message):
            continue
        if any(products[pid]["name"] in message for pid in ids):
            continue
        quantities = [value for value in range(1, 100) if literal_quantity(message, term, value)]
        names = "、".join(products[pid]["name"] for pid in sorted(ids))
        quantity = f"原请求数量为{quantities[0]}件，不能自行拆分到多个规格。" if len(quantities) == 1 else "数量需另行核对。"
        return f"查询到多个商品规格：{names}。请先选择具体规格。{quantity}尚未授权、未创建草稿。"
    return None


def grounded_fallback_args(message, products):
    """Only exact, fully covered quantity/name clauses may recover a missing preview call."""
    clauses = re.findall(r"([0-9一二三四五六七八九十两]+)\s*" + UNITS
                         + r"\s*([^\s，,。；;、]+)", message)
    if not clauses:
        named = re.search(r"(?:购买|下单|订购|想买|帮我买)\s*([^\s，,。；;、]+)", message)
        matches = [pid for pid, product in products.items() if named and product["name"] == named[1]]
        return {"items": [{"medicineId": matches[0], "quantity": None}]} if len(matches) == 1 else None
    if len(clauses) > 10:
        return None
    lines = []
    for number, name in clauses:
        matches = [pid for pid, product in products.items() if product["name"] == name]
        quantities = [value for value in range(1, 100) if number in number_texts(value)]
        if len(matches) != 1 or len(quantities) != 1:
            return None
        lines.append({"medicineId": matches[0], "quantity": quantities[0]})
    if len({line["medicineId"] for line in lines}) != len(lines):
        return None
    return {"items": lines}

