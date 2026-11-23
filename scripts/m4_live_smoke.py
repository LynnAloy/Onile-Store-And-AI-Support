"""Actual native model tool calls, real Java/MySQL reads, synthetic fixtures only."""
import json
import sys
import time
import uuid

from m3_live_smoke import ProfileSmoke
from live_smoke import check
from local_stack import RUN, ensure_private, query


class ReadToolSmoke(ProfileSmoke):
    def ask(self, cid, agent, prompt, expected_tool):
        frames = self.frames(cid, agent, prompt)
        check(frames[-1][0] == "done", "Tool conversation failed: " +
              next((data.get("code", "") for kind, data in frames if kind == "error"), "missing done"))
        results = [data for kind, data in frames if kind == "tool_result" and data["tool"] == expected_tool]
        check(bool(results), "Model did not return native " + expected_tool + " call; actual tools: " +
              ",".join(data["tool"] for kind, data in frames if kind == "tool_result"))
        return results[-1], frames

    def run(self):
        users, agents = [], []
        for name in self.names:
            self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
            token = self.request("POST", "/api/auth/login",
                                 data={"userId": name, "password": self.password})["token"]
            users.append(token)
            agents.append(self.request("POST", "/api/auth/agent-token", token)["token"])
        a, b = users
        agent, agent_b = agents
        self.request("POST", "/api/auth/activate-wallet", a, {"password": self.pin})
        query(self.conn, "INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)", (self.card,))
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,0.37,1)", (self.product_name,))
            self.product = cursor.lastrowid
        self.persist_fixture()
        self.qualify_fixture()
        self.request("POST", "/api/wallet/recharge", a, {"cardId": self.card})
        paid = self.request("POST", "/api/orders", a, {
            "recipientName": "合成测试", "recipientPhone": "13800138000", "recipientAddress": "合成测试地址",
            "walletPassword": self.pin, "items": [{"medicineId": self.product, "quantity": 1}],
        }, headers={"Idempotency-Key": str(uuid.uuid4())})
        oid = paid["orderId"]
        before = query(self.conn, "SELECT stock FROM medicines WHERE id=%s", (self.product,))
        balance = query(self.conn, "SELECT balance FROM users WHERE user_id=%s", (self.names[0],))
        order_count = query(self.conn, "SELECT count(*) FROM orders")

        cid = self.request("POST", "/ai/v1/conversations", agent, {"title": "合成工具联调"}, expected=201)["id"]
        result, frames = self.ask(cid, agent, "请查一下名称为“" + self.product_name +
                                  "”的商品当前价格和库存，简短回答。", "search_medicines")
        products = result["result"]["products"]
        check(any(p["id"] == self.product and p["price"] == "0.37" and p["stock"] == 0 for p in products),
              "Catalog snapshot differs from MySQL")
        self.record("Native model search_medicines -> real Java catalog -> exact money and zero-stock card")

        result, frames = self.ask(cid, agent, "请实时查询商品ID " + str(self.product) +
                                  " 的详情，只简短说明价格和库存。", "get_medicine")
        check(result["result"]["products"][0]["id"] == self.product, "Detail product ID mismatch")
        self.record("Native get_medicine call and server-bound product ID")

        result, frames = self.ask(cid, agent, "请查询我本人订单 " + oid +
                                  " 的实际状态与总金额，简短回答。", "get_my_order")
        order = result["result"]["order"]
        check(order["orderId"] == oid and order["totalPrice"] == "0.37", "Order tool mismatch")
        check("13800138000" not in json.dumps(result), "Recipient information leaked to tool output")
        self.record("Native get_my_order reads owned order without recipient details")

        cid_b = self.request("POST", "/ai/v1/conversations", agent_b, {"title": "合成隔离联调"}, expected=201)["id"]
        result, frames = self.ask(cid_b, agent_b, "请实时查询我的订单号 " + oid +
                                  "，简短回答查询结果。", "get_my_order")
        check(result["result"].get("code") == "NOT_FOUND", "Cross-user order should not be readable")
        self.record("Other user's order is returned as NOT_FOUND through actual tool calling")

        result, frames = self.ask(cid_b, agent_b,
                                  "请使用search_medicines查询名称包含‘不存在的星际商品’的商品，limit为5，简短回答。",
                                  "search_medicines")
        check(result["result"].get("products") == [], "No-match query should be empty")
        self.record("Actual no-match tool result is shown as an empty catalog")

        history = self.request("GET", f"/ai/v1/conversations/{cid}/messages", agent)
        check(all(len(turn["toolEvents"]) >= 2 for turn in history["turns"]), "Tool traces not persisted")
        last = history["turns"][-1]
        repeated = self.stream(cid, agent, last["message"], last["requestId"])
        check(repeated["replayed"], "Completed tool turn should replay cached result")
        check(query(self.conn, "SELECT stock FROM medicines WHERE id=%s", (self.product,)) == before,
              "Read tools changed stock")
        check(query(self.conn, "SELECT balance FROM users WHERE user_id=%s", (self.names[0],)) == balance,
              "Read tools changed balance")
        check(query(self.conn, "SELECT count(*) FROM orders") == order_count, "Read tools created orders")
        self.record("Persisted tool history/replay and unchanged stock, balance and order count")


def main():
    ensure_private()
    smoke = ReadToolSmoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception:
            failure = (failure or "") + " Scoped M4 fixture cleanup failed"
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "realServices": True,
              "nativeToolProtocolRequired": True, "allThreeNativeToolsVerified": len(smoke.results) >= 3,
              "model": smoke.values.get("OLLAMA_MODEL"), "checks": smoke.results, "passed": failure is None,
              "failure": failure, "syntheticFixturesOnly": True, "credentialsLogged": False}
    (RUN / "m4-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())

