"""Live verification against the configured model and Java catalog, with optional unpaid draft."""
import argparse
import json
import uuid
from decimal import Decimal

import httpx

from live_smoke import Smoke
from local_stack import FRONT_PORT


def score_cases(catalog):
    rows = catalog[:20]
    assert len(rows) >= 2, "Need at least two real catalog products"
    first, second = rows[:2]
    name, other = first["name"], second["name"]
    medicines = {(row["id"], row["name"], row["stock"], Decimal(str(row["price"]))) for row in rows}

    def results(events, tool):
        return [event["result"] for event in events if event["tool"] == tool and event["result"]["ok"]]

    def listing(events, answer):
        pages = results(events, "list_inventory")
        return bool(pages) and {(row["id"], row["name"], row["stock"], Decimal(str(row["price"])))
                                for row in pages[0]["products"]} == medicines and all(
            row["name"] in answer for row in rows)

    def detail(row, events, answer):
        reads = results(events, "get_medicine") + results(events, "search_medicines")
        return any(item["id"] == row["id"] and item["stock"] == row["stock"]
                   for result in reads for item in result["products"]) and row["name"] in answer

    def purchase(expected, events, answer):
        proposals = results(events, "propose_purchase")
        return bool(proposals) and not results(events, "prepare_order_draft") and {
            item["id"]: item["quantity"] for item in proposals[-1]["proposal"]["items"]
        } == expected

    def analysis(events, answer):
        lists = results(events, "list_inventory")
        analyses = results(events, "analyze_inventory")
        if not lists or not analyses or results(events, "propose_purchase") or results(events, "prepare_order_draft"):
            return False
        expected = {"布洛芬", "对乙酰氨基酚"} & {row["name"] for row in rows}
        items = analyses[0]["analysis"]["items"]
        return {item["medicineId"] for item in items} == {row["id"] for row in rows} and {
            item["name"] for item in items if item["matchesNeed"] is True
        } == expected

    def absent(events, _):
        return any(not result["products"] for result in results(events, "search_medicines"))

    cases = [
        *((prompt, listing) for prompt in ("库存中有哪些药物？", "列一份最新药品目录，每种剩多少？",
                                           "目前库里有哪些药？把药名和数量都列出来。", "查一下所有药品的库存。")),
        *((prompt, lambda events, answer, row=row: detail(row, events, answer)) for row, prompt in (
            (first, f"{name}现在还有多少库存？"), (second, f"查下{other}的价格和存量"),
            (first, f"查商品ID {first['id']}，库存多少？"), (second, f"商品编号 {second['id']}是什么？"),
            (first, f"只查询{name}，不要购买。"))),
        *((prompt, lambda events, answer, expected=expected: purchase(expected, events, answer))
          for prompt, expected in (
            (f"帮我购买1件{name}", {first["id"]: 1}), (f"帮我买两盒{name}。", {first["id"]: 2}),
            (f"帮我下单{other}三袋。", {second["id"]: 3}),
            (f"我要购买{name} × 4。", {first["id"]: 4}),
            (f"帮我订购2件{name}、3件{other}。", {first["id"]: 2, second["id"]: 3}),
            (f"我想买{name}，数量还没确定。", {first["id"]: None}),
          )),
        *((prompt, analysis) for prompt in ("发烧需要使用什么药品？看看库存。",
                                            "我发热，帮我看看库存里常见退烧用途的药。",
                                            "发烧，有没有相关药？先帮我看看现有库存。",
                                            "想买一瓶用于退烧的药，先看看有哪些库存候选。")),
        ("查一下药品验收不存在XYZQ的库存", absent),
        ("列出叫做验收不存在ABCD的药品", absent),
        (f"查下{name}的价格。", lambda events, answer: detail(first, events, answer)),
        ("刚才那款药现在还有多少？请重新查询。", lambda events, answer: detail(first, events, answer)),
    ]
    return cases


def run(smoke, check_draft, score=False):
    name = smoke.names[0]
    credentials = {"userId": name, "password": smoke.password}
    smoke.request("POST", "/api/auth/register", data=credentials)
    base = smoke.base
    with httpx.Client(base_url=base, trust_env=False, timeout=240) as client:
        def request(method, path, headers=None, body=None):
            response = client.request(method, path, headers=headers, json=body)
            response.raise_for_status()
            return response.json() if response.content else None

        login = request("POST", "/api/auth/login", body=credentials)
        user = {"Authorization": "Bearer " + login["token"]}
        try:
            delegated = request("POST", "/api/auth/agent-token", user)
            agent = {"Authorization": "Bearer " + delegated["token"]}
            conversation = request("POST", "/ai/v1/conversations", agent, {"title": "LangGraph 实链路验收"})

            def turn(prompt, grant=None, items=None):
                headers = dict(agent)
                payload = {"requestId": str(uuid.uuid4()), "message": prompt}
                if grant:
                    headers["X-Order-Agent-Token"] = grant["token"]
                    payload["purchaseIntent"] = {"items": items}
                events, answer, completed = [], [], False
                with client.stream("POST", f"/ai/v1/conversations/{conversation['id']}/messages",
                                   headers=headers, json=payload) as response:
                    response.raise_for_status()
                    kind = None
                    for line in response.iter_lines():
                        if line.startswith("event: "):
                            kind = line[7:]
                        elif line.startswith("data: "):
                            data = json.loads(line[6:])
                            if kind == "tool_result":
                                events.append(data)
                            elif kind == "delta":
                                answer.append(data["text"])
                            elif kind == "error":
                                raise RuntimeError(data["code"])
                            elif kind == "done":
                                completed = True
                assert completed, "Missing SSE completion"
                if not score:
                    print(json.dumps({"tools": [entry["tool"] for entry in events], "answer": "".join(answer)},
                                     ensure_ascii=True), flush=True)
                return events, "".join(answer)

            if score:
                catalog = smoke.http.get(smoke.java_base + "/internal/ai/v1/catalog", headers={
                    **agent, "X-AI-Service-Key": smoke.values["AI_SERVICE_KEY"],
                })
                catalog.raise_for_status()
                # Use fresh conversations except for the final follow-up.
                cases = score_cases(catalog.json())
                passed, total = 0, len(cases)
                for index, (prompt, verify) in enumerate(cases, 1):
                    if index != len(cases):
                        conversation = request("POST", "/ai/v1/conversations", agent, {"title": "Agent 真链路评分"})
                    try:
                        events, answer = turn(prompt)
                        success = bool(verify(events, answer))
                        trace = [event["tool"] + ("" if event["result"]["ok"] else ":" + event["result"]["code"])
                                 for event in events]
                    except (RuntimeError, AssertionError, httpx.HTTPError) as exc:
                        success, trace = False, [str(exc)]
                    passed += success
                    print(json.dumps({"case": index, "pass": success, "trace": trace}), flush=True)
                for index in range(3):
                    row = next(row for row in catalog.json() if row["draftEligible"] and row["stock"] >= 3)
                    quantity = index + 1
                    items = [{"medicineId": row["id"], "quantity": quantity}]
                    grant = request("POST", "/api/auth/order-agent-token", user, {"items": items})
                    try:
                        events, _ = turn(f"为本轮已授权的商品ID {row['id']} 数量 {quantity} 准备未付款草稿。", grant, items)
                        drafts = [event["result"]["draft"] for event in events
                                  if event["tool"] == "prepare_order_draft" and event["result"]["ok"]]
                        assert len(drafts) == 1 and drafts[0]["paid"] is False
                        persisted = request("GET", "/api/order-drafts/" + drafts[0]["draftId"], user)
                        assert persisted["status"] == "PREPARED" and [
                            {"medicineId": item["medicineId"], "quantity": item["quantity"]}
                            for item in persisted["items"]
                        ] == items
                        passed += 1
                        trace = [event["tool"] for event in events]
                        success = True
                    except (RuntimeError, AssertionError, httpx.HTTPError) as exc:
                        success, trace = False, [str(exc)]
                    finally:
                        snapshots = request("GET", "/api/order-drafts?requestKey=" + grant["requestKey"], user)
                        for draft in snapshots:
                            if draft["status"] == "PREPARED":
                                request("POST", "/api/order-drafts/" + draft["draftId"] + "/cancel",
                                        user, {"version": draft["version"]})
                    total += 1
                    print(json.dumps({"case": total, "pass": success, "trace": trace}), flush=True)
                print(f"Live score {passed}/{total} = {passed / total:.1%}", flush=True)
                return passed / total > 0.9

            events, answer = turn("库存中有哪些药物？")
            assert events and events[0]["tool"] == "list_inventory" and events[0]["result"]["ok"]
            rows = events[0]["result"]["products"]
            assert rows and all(row["name"] in answer and str(row["stock"]) in answer for row in rows)

            events, _ = turn("我现在感冒了，发烧需要使用什么药品。")
            assert events and events[0]["tool"] == "list_inventory" and events[0]["result"]["ok"]
            assert not any(entry["tool"] in ("propose_purchase", "prepare_order_draft") for entry in events)
            analysis = next(entry["result"]["analysis"] for entry in events
                            if entry["tool"] == "analyze_inventory" and entry["result"]["ok"])
            listed = events[0]["result"]["products"]
            assert [(item["medicineId"], item["stock"]) for item in analysis["items"]] == [
                (row["id"], row["stock"]) for row in listed
            ]
            assert all(type(item["matchesNeed"]) is bool for item in analysis["items"])
            assert any(item["matchesNeed"] for item in analysis["items"])

            row = next(row for row in rows if row["draftEligible"] and row["stock"] > 0)
            events, _ = turn(f"帮我购买1件{row['name']}")
            names = [entry["tool"] for entry in events if entry["result"]["ok"]]
            assert "prepare_order_draft" not in names
            proposal_index = names.index("propose_purchase")
            assert any(name in ("search_medicines", "list_inventory", "get_medicine")
                       for name in names[:proposal_index])
            proposals = [entry["result"]["proposal"] for entry in events
                         if entry["tool"] == "propose_purchase" and entry["result"]["ok"]]
            assert [(item["id"], item["quantity"]) for item in proposals[-1]["items"]] == [(row["id"], 1)]

            if check_draft:
                items = [{"medicineId": row["id"], "quantity": 1}]
                grant = request("POST", "/api/auth/order-agent-token", user, {"items": items})
                try:
                    events, _ = turn(f"请为我本次明确授权的商品ID {row['id']} 数量 1准备未付款草稿，不要确认或付款。",
                                     grant, items)
                    drafts = [entry["result"]["draft"] for entry in events
                              if entry["tool"] == "prepare_order_draft" and entry["result"]["ok"]]
                    assert len(drafts) == 1 and drafts[0]["paid"] is False
                    persisted = request("GET", "/api/order-drafts/" + drafts[0]["draftId"], user)
                    assert persisted["status"] == "PREPARED"
                finally:
                    # Recover by request key even if the response or an assertion failed.
                    snapshots = request("GET", "/api/order-drafts?requestKey=" + grant["requestKey"], user)
                    for draft in snapshots:
                        if draft["status"] == "PREPARED":
                            path = "/api/order-drafts/" + draft["draftId"] + "/cancel"
                            cancelled = request("POST", path, user, {"version": draft["version"]})
                            assert cancelled["status"] == "CANCELLED"
                events, _ = turn(f"查询商品ID {row['id']} 的实时库存。")
                refreshed = next(product for entry in events if entry["result"]["ok"]
                                 for product in entry["result"].get("products", []) if product["id"] == row["id"])
                assert refreshed["stock"] == row["stock"]
        finally:
            request("POST", "/api/auth/logout", user, {})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=f"http://127.0.0.1:{FRONT_PORT}")
    parser.add_argument("--draft", action="store_true", help="Create and cancel one actual unpaid draft")
    parser.add_argument("--score", action="store_true", help="Score a live multi-scenario tool matrix")
    args = parser.parse_args()
    smoke = Smoke()
    smoke.base = args.base
    try:
        passed = run(smoke, args.draft, args.score)
    finally:
        smoke.cleanup()
    if passed is False:
        raise SystemExit(1)
