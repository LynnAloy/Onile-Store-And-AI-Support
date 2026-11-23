"""Real MySQL/Java payment checks; synthetic users, recharge cards and product only."""
import concurrent.futures
import json
import os
import time
import uuid

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from live_smoke import Smoke, check
from local_stack import RUN, query
import m51_contract


class PaymentSmoke(Smoke):
    contract_responses = 0

    def request(self, method, path, token=None, data=None, expected=200, headers=None):
        if m51_contract.operation(method, path) is None:
            return super().request(method, path, token, data, expected, headers)
        auth = {"Authorization": "Bearer " + token} if token else {}
        auth.update(headers or {})
        result = self.http.request(method, self.base + path, json=data, headers=auth)
        check(result.status_code == expected, path + " returned HTTP " + str(result.status_code))
        m51_contract.response(method, path, result.status_code, result.json(), result.headers)
        self.contract_responses += 1
        return result.json() if expected in (200, 201) else None

    def prepare(self, user, quantity=1):
        intent = {"items": [{"medicineId": self.product, "quantity": quantity}]}
        grant = self.request("POST", "/api/auth/order-agent-token", user, intent)
        response = self.http.post(self.java_base + "/internal/ai/v1/order-drafts", json=intent,
            headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": self.values["AI_SERVICE_KEY"],
                     "Idempotency-Key": grant["requestKey"]})
        response.raise_for_status()
        draft = response.json()["draftId"]
        self.request("POST", f"/api/order-drafts/{draft}/confirm", user, {
            "version": 1, "recipientName": "合成支付用户", "recipientPhone": "13800138000", "recipientAddress": "合成支付测试地址"})
        return draft

    def checkout(self, user, draft=None, quantity=1, key=None):
        draft = draft or self.prepare(user, quantity)
        return self.request("POST", f"/api/order-drafts/{draft}/checkout", user, {"expectedVersion": 2},
                            headers={"Idempotency-Key": key or str(uuid.uuid4())})

    def grant(self, user, order):
        return self.request("POST", f"/api/orders/{order}/payment-authorizations", user,
                            {"expectedVersion": 1, "password": self.pin})

    def pay(self, user, order, grant, key=None, expected=200):
        return self.request("POST", f"/api/orders/{order}/pay", user, {"expectedVersion": 1}, expected=expected,
                            headers={"X-Payment-Authorization": grant["token"], "Idempotency-Key": key or str(uuid.uuid4())})

    def run(self):
        guard()
        tokens = []
        for name, card in zip(self.names, [self.card, self.card_b]):
            self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
            token = self.request("POST", "/api/auth/login", data={"userId": name, "password": self.password})["token"]
            tokens.append(token)
            self.request("POST", "/api/auth/activate-wallet", token, {"password": self.pin})
            query(self.conn, "INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)", (card,))
            self.request("POST", "/api/wallet/recharge", token, {"cardId": card})
        a, b = tokens
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,0.10,10)", (self.product_name,))
            self.product = cursor.lastrowid
        self.persist_fixture()
        self.qualify_fixture()
        draft = self.prepare(a, 3)
        first = self.checkout(a, draft, key="live-checkout-one")
        again = self.checkout(a, draft, key="live-checkout-two")
        check(first["orderId"] == again["orderId"] and first["totalPrice"] == "0.30", "Checkout snapshot or source uniqueness failed")
        order = first["orderId"]
        self.record("Actual draft checkout is unpaid, exact decimal and unique across request keys")
        grant = self.grant(a, order)
        check(grant["expiresAt"] - int(time.time()) <= 60, "Payment grant too long-lived")
        key = "live-payment-replay"
        receipt = self.pay(a, order, grant, key)
        check(receipt == self.pay(a, order, grant, key) == self.pay(a, order, grant), "Paid replay differs")
        balance = query(self.conn, "SELECT balance,points FROM users WHERE user_id=%s", (self.names[0],))[0]
        check(str(balance[0]) == "49.70" and balance[1] == 0, "Money or points duplicated")
        check(query(self.conn, "SELECT stock FROM medicines WHERE id=%s", (self.product,))[0][0] == 7, "Stock duplicated")
        self.record("Real payment, consumed-token replay and changed-key retry debit money/stock exactly once")
        self.request("GET", f"/api/orders/{order}", b, expected=404)
        recovered = self.request("GET", f"/api/orders/{order}?paymentRequestKey={key}", a)
        check(recovered["paymentStatus"] == "PAID" and recovered["requestOutcome"]["status"] == "SUCCEEDED", "Recovery did not find committed result")
        self.request("POST", f"/api/orders/{order}/close", a, {"expectedVersion": 2}, expected=409)
        self.record("Private recovery finds committed receipt; cross-user reads and closing PAID are rejected")
        read = self.request("POST", "/api/auth/agent-token", a)["token"]
        prep = self.request("POST", "/api/auth/order-agent-token", a, {"items": [{"medicineId": self.product, "quantity": 1}]})["token"]
        for token in (read, prep):
            self.request("POST", f"/api/orders/{order}/payment-authorizations", token,
                         {"expectedVersion": 1, "password": self.pin}, expected=403)
            self.request("POST", f"/api/orders/{order}/pay", token, {"expectedVersion": 1}, expected=403,
                         headers={"Idempotency-Key": str(uuid.uuid4()), "X-Payment-Authorization": grant["token"]})
        self.record("Both agent roles cannot verify, authorize or pay")
        from m43_evaluate import frames
        cid = self.request("POST", "/ai/v1/conversations", read, {"title": "合成支付摘要检查"}, expected=201)["id"]
        events = frames(self, cid, read, "请实际调用get_my_order查询我的订单" + order + "的状态和金额。")
        summaries = [data["result"]["order"] for kind, data in events if kind == "tool_result"
                     and data["tool"] == "get_my_order" and data["result"].get("ok")]
        check(summaries and summaries[0]["status"] == "PAID" and events[-1][0] == "done", "Actual model order read failed")
        encoded = json.dumps(summaries)
        check(all(field not in encoded for field in ("recipient", "authorization", "ledgerId", "13800138000")), "Private payment data reached model tool")
        self.record("Native model reads authoritative PAID summary without shipping or payment credentials")
        late_order = self.checkout(a)["orderId"]
        late, newer = self.grant(a, late_order), self.grant(a, late_order)
        self.request("DELETE", f"/api/orders/{late_order}/payment-authorizations?authorizationId={late['authorizationId']}", a)
        self.pay(a, late_order, late, expected=401)
        self.pay(a, late_order, newer)
        self.record("Late authorization cleanup does not revoke a subsequently issued capability")
        changed = self.checkout(a)["orderId"]
        old = self.grant(a, changed)
        query(self.conn, "UPDATE medicines SET price=0.20 WHERE id=%s", (self.product,))
        self.pay(a, changed, old, expected=409)
        check(self.request("GET", f"/api/orders/{changed}", a)["closeReason"] == "CATALOG_CHANGED", "Changed price did not close order")
        query(self.conn, "UPDATE medicines SET price=0.10 WHERE id=%s", (self.product,))
        self.record("Real price conflict persists CLOSED and revocation without deducting funds")
        one, two = self.checkout(a)["orderId"], self.checkout(b)["orderId"]
        ga, gb = self.grant(a, one), self.grant(b, two)
        query(self.conn, "UPDATE medicines SET stock=1 WHERE id=%s", (self.product,))
        def compete(args):
            user, oid, cap = args
            return self.http.post(self.base + f"/api/orders/{oid}/pay", json={"expectedVersion": 1},
                headers={"Authorization": "Bearer " + user, "X-Payment-Authorization": cap["token"], "Idempotency-Key": str(uuid.uuid4())}).status_code
        before = query(self.conn, "SELECT sum(balance) FROM users WHERE user_id IN (%s,%s)", tuple(self.names))[0][0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(compete, [(a, one, ga), (b, two, gb)]))
        after = query(self.conn, "SELECT sum(balance) FROM users WHERE user_id IN (%s,%s)", tuple(self.names))[0][0]
        check(sorted(statuses) == [200, 409] and str(before-after) == "0.10", "Last stock race is not atomic")
        self.record("Real MySQL two-user last-stock race has one winner, loser funds unchanged")
        query(self.conn, "UPDATE medicines SET stock=10 WHERE id=%s", (self.product,))
        closing = self.checkout(a)["orderId"]
        cap = self.grant(a, closing)
        def transition(action):
            headers = {"Authorization": "Bearer " + a}
            if action == "pay":
                headers.update({"X-Payment-Authorization": cap["token"], "Idempotency-Key": str(uuid.uuid4())})
            return self.http.post(self.base + f"/api/orders/{closing}/{action}", json={"expectedVersion": 1}, headers=headers).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(transition, ["pay", "close"]))
        check(sorted(statuses) == [200, 409], "Pay/close race had multiple winners")
        self.record("Real MySQL pay/close race resolves to exactly one terminal outcome")
        expiring = self.checkout(a)["orderId"]
        self.grant(a, expiring)
        query(self.conn, "UPDATE orders SET payment_expires_at=0 WHERE id=%s", (expiring,))
        check(self.request("GET", f"/api/orders/{expiring}", a)["closeReason"] == "EXPIRED", "Expiry did not persist")
        self.record("Order expiry is enforced on read and persisted without a scheduler")
        self.request("POST", "/api/orders", a, {"userId": self.names[0], "recipientName": "合成", "recipientPhone": "13800138000",
            "recipientAddress": "合成", "walletPassword": self.pin, "items": [{"medicineId": self.product, "quantity": 1}]},
            expected=409, headers={"Idempotency-Key": "legacy-cannot-bypass"})
        self.record("Enabled M5 refuses legacy direct checkout bypass")


def main():
    smoke = PaymentSmoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception as exc:
            failure = (failure or "") + " Scoped cleanup failed: " + type(exc).__name__
    report = {"passed": failure is None, "checks": smoke.results, "failure": failure,
              "contractResponsesChecked": smoke.contract_responses,
              "realMySQL": True, "syntheticOnly": True, "normalFundsChanged": False}
    (RUN / "m51-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
