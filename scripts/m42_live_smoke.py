"""M4.2 native draft tool and actual Java/MySQL state machine; synthetic users/products only."""
import json
import sys
import time
import uuid
import concurrent.futures

from live_smoke import Smoke, check
from local_stack import RUN, ensure_private, query


class DraftSmoke(Smoke):
    def internal(self, method, path, grant, data=None, expected=200, key=None):
        response = self.http.request(method, self.java_base + "/internal/ai/v1/" + path, json=data,
            headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": self.values["AI_SERVICE_KEY"],
                     "Idempotency-Key": key or grant["requestKey"]})
        check(response.status_code == expected, "Internal draft HTTP mismatch: " + str(response.status_code))
        return response.json() if response.content else {}

    def native_prepare(self, cid, read_token, grant, items):
        parsed = []
        with self.http.stream("POST", self.base + f"/ai/v1/conversations/{cid}/messages",
            headers={"Authorization": "Bearer " + read_token, "X-Order-Agent-Token": grant["token"]},
            json={"requestId": str(uuid.uuid4()), "message": "请调用prepare_order_draft，为我本次明确授权的商品数量准备未付款草稿，不要确认或付款。",
                  "purchaseIntent": {"items": items}}) as response:
            check(response.status_code == 200, "Draft AI stream did not start")
            kind = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    item = json.loads(line[5:].strip())
                    parsed.append((kind, item))
                    if kind == "error":
                        raise RuntimeError("Native draft tool failed: " + item.get("code", "UNKNOWN"))
        check(parsed[-1][0] == "done", "Native draft turn did not complete")
        results = [data["result"] for kind, data in parsed
                   if kind == "tool_result" and data["tool"] == "prepare_order_draft"]
        check(results and results[0]["ok"], "Model did not perform native authorized draft preparation")
        return results[0]["draft"]

    def run(self):
        users, agents = [], []
        for name in self.names:
            self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
            token = self.request("POST", "/api/auth/login",
                                 data={"userId": name, "password": self.password})["token"]
            users.append(token)
            agents.append(self.request("POST", "/api/auth/agent-token", token)["token"])
        a, b = users
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,0.37,10)", (self.product_name,))
            self.product = cursor.lastrowid
        self.persist_fixture()
        items = [{"medicineId": self.product, "quantity": 2}]
        intent = {"items": items}
        grant = self.request("POST", "/api/auth/order-agent-token", a, intent)
        unknown = self.internal("POST", "order-drafts", grant, intent, expected=409)
        check(unknown["code"] == "SALE_NOT_ALLOWED", "Unknown product bypassed qualification")
        self.qualify_fixture()
        query(self.conn, "UPDATE medicines SET sale_classification='RX' WHERE id=%s", (self.product,))
        check(self.internal("POST", "order-drafts", grant, intent, expected=409)["code"] == "SALE_NOT_ALLOWED",
              "RX product bypassed prescription gate")
        query(self.conn, "UPDATE medicines SET sale_classification='OTC' WHERE id=%s", (self.product,))
        self.record("Default UNKNOWN/PENDING and RX qualification gates block draft writes")

        before = query(self.conn, "SELECT (SELECT balance FROM users WHERE user_id=%s),"
                       "(SELECT stock FROM medicines WHERE id=%s),(SELECT count(*) FROM orders)",
                       (self.names[0], self.product))
        self.request("GET", "/api/order-drafts", grant["token"], expected=403)
        read_grant = {"token": agents[0], "requestKey": grant["requestKey"]}
        self.internal("POST", "order-drafts", read_grant, intent, expected=403)
        self.record("Order preparation scope is separate from read delegation and USER confirmation")

        cid = self.request("POST", "/ai/v1/conversations", agents[0], {"title": "合成草稿联调"}, expected=201)["id"]
        draft = self.native_prepare(cid, agents[0], grant, items)
        did = draft["draftId"]
        check(draft["status"] == "PREPARED" and draft["totalPrice"] == "0.74" and draft["paid"] is False,
              "Native draft snapshot mismatch")
        repeated = self.internal("POST", "order-drafts", grant, intent)
        check(repeated["draftId"] == did, "Repeated request created a different draft")
        self.internal("POST", "order-drafts", grant, {"items": [{"medicineId": self.product, "quantity": 3}]}, expected=409)
        self.internal("POST", "order-drafts", grant, intent, expected=409, key=str(uuid.uuid4()))
        recovered = self.request("GET", "/api/order-drafts?requestKey=" + grant["requestKey"], a)
        check(len(recovered) == 1 and recovered[0]["draftId"] == did, "Draft recovery by key failed")
        self.record("Native model prepare_order_draft, authoritative amount, durable idempotency and recovery")

        self.request("GET", "/api/order-drafts/" + did, b, expected=404)
        confirmation = {"version": 1, "recipientName": "合成收货人", "recipientPhone": "13800138000",
                        "recipientAddress": "合成地址，仅用于联调"}
        self.request("POST", "/api/order-drafts/" + did + "/confirm", b, confirmation, expected=404)
        self.request("POST", "/api/order-drafts/" + did + "/confirm", grant["token"], confirmation, expected=403)
        self.record("Cross-user draft ownership and agent prohibition on confirmation")

        query(self.conn, "UPDATE medicines SET price=0.42 WHERE id=%s", (self.product,))
        check(self.request("GET", "/api/order-drafts/" + did, a)["canConfirm"] is False, "Price change not shown")
        response = self.http.post(self.base + "/api/order-drafts/" + did + "/confirm",
                                   headers={"Authorization": "Bearer " + a}, json=confirmation)
        check(response.status_code == 409 and response.json()["code"] == "PRICE_CHANGED", "Price was silently accepted")
        query(self.conn, "UPDATE medicines SET price=0.37,stock=1 WHERE id=%s", (self.product,))
        self.request("POST", "/api/order-drafts/" + did + "/confirm", a, confirmation, expected=409)
        query(self.conn, "UPDATE medicines SET stock=10,qualification_version=2 WHERE id=%s", (self.product,))
        self.request("POST", "/api/order-drafts/" + did + "/confirm", a, confirmation, expected=409)
        query(self.conn, "UPDATE medicines SET qualification_version=1 WHERE id=%s", (self.product,))
        self.record("Actual price, stock and qualification changes require fresh review")

        confirmed = self.request("POST", "/api/order-drafts/" + did + "/confirm", a, confirmation)
        again = self.request("POST", "/api/order-drafts/" + did + "/confirm", a, confirmation)
        check(confirmed["status"] == "CONFIRMED" and confirmed["paid"] is False and again["version"] == 2,
              "Confirm not idempotent or incorrectly marked paid")
        internal = self.internal("POST", "order-drafts", grant, intent)
        check("recipientPhone" not in internal and "recipientAddress" not in internal, "Shipping leaked to model")
        after = query(self.conn, "SELECT (SELECT balance FROM users WHERE user_id=%s),"
                      "(SELECT stock FROM medicines WHERE id=%s),(SELECT count(*) FROM orders)",
                      (self.names[0], self.product))
        check(before == after, "Preparation or confirmation changed money, stock or completed orders")
        self.record("USER confirmation is idempotent, unpaid, private and does not change inventory or balance")

        self.request("DELETE", "/api/auth/order-agent-token", a)
        self.internal("POST", "order-drafts", grant, intent, expected=401)
        check(self.request("GET", "/api/order-drafts/" + did, a)["status"] == "CONFIRMED",
              "Revocation deleted a durable draft")
        grant2 = self.request("POST", "/api/auth/order-agent-token", a, intent)
        draft2 = self.internal("POST", "order-drafts", grant2, intent)
        self.request("POST", "/api/order-drafts/" + draft2["draftId"] + "/cancel", a, {"version": 1})
        self.request("POST", "/api/order-drafts/" + draft2["draftId"] + "/confirm", a, confirmation, expected=409)
        grant3 = self.request("POST", "/api/auth/order-agent-token", a, intent)
        draft3 = self.internal("POST", "order-drafts", grant3, intent)
        query(self.conn, "UPDATE order_drafts SET expires_at=0 WHERE id=%s", (draft3["draftId"],))
        self.request("POST", "/api/order-drafts/" + draft3["draftId"] + "/confirm", a, confirmation, expected=409)
        self.record("Revocation preserves drafts; cancellation and expiry reject confirmation")

        grant4 = self.request("POST", "/api/auth/order-agent-token", a, intent)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            prepared = list(pool.map(lambda _: self.internal("POST", "order-drafts", grant4, intent), range(2)))
        check(prepared[0]["draftId"] == prepared[1]["draftId"], "Concurrent preparation created duplicate drafts")
        concurrent_id = prepared[0]["draftId"]
        def transition(action):
            body = confirmation if action == "confirm" else {"version": 1}
            return self.http.post(self.base + "/api/order-drafts/" + concurrent_id + "/" + action,
                                  headers={"Authorization": "Bearer " + a}, json=body).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(transition, ["confirm", "cancel"]))
        check(sorted(statuses) == [200, 409], "Concurrent confirm/cancel did not have exactly one winner")
        self.record("Real MySQL concurrent prepare is idempotent and confirm/cancel has one winner")

        late = self.request("POST", "/api/auth/order-agent-token", a, intent)
        newer = self.request("POST", "/api/auth/order-agent-token", a, intent)
        path = "/api/auth/order-agent-token?requestKey=" + late["requestKey"]
        self.request("DELETE", path, b)
        self.internal("POST", "order-drafts", late, intent)
        self.request("DELETE", path, a)
        self.internal("POST", "order-drafts", late, intent, expected=401)
        self.internal("POST", "order-drafts", newer, intent)
        self.request("DELETE", "/api/auth/order-agent-token?requestKey=invalid", a, expected=400)
        self.internal("POST", "order-drafts", newer, intent)
        self.record("Scoped late-grant revocation preserves newer grants and rejects cross-user or malformed cleanup")

        self.request("POST", "/api/auth/logout", a)
        self.internal("POST", "order-drafts", grant3, intent, expected=401)
        self.request("GET", "/api/user/profile", b)
        self.record("Parent logout invalidates order preparation without affecting another user")


def main():
    ensure_private()
    smoke = DraftSmoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception:
            failure = (failure or "") + " Scoped M4.2 cleanup failed"
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "realServices": True,
              "model": smoke.values.get("OLLAMA_MODEL"), "checks": smoke.results,
              "passed": failure is None, "failure": failure, "syntheticFixturesOnly": True,
              "credentialsLogged": False}
    (RUN / "m42-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())

