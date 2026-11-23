"""Owned synthetic UI/model fixtures and end-to-end checks on the isolated demo only."""
import argparse
import json
import os
import secrets
import sqlite3
import uuid

import httpx

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from local_stack import RUN, ROOT, database, query, protect, target_fingerprint

FILE = RUN / "m6-ui-fixture.json"


def request(client, method, path, token=None, data=None, expected=200):
    response = client.request(method, path, headers={"Authorization": "Bearer " + token} if token else {}, json=data)
    if response.status_code != expected:
        raise RuntimeError(path + " returned " + str(response.status_code))
    return response.json() if response.content else None


def load():
    values = guard()
    record = json.loads(FILE.read_text(encoding="utf-8"))
    if record["targetFingerprint"] != target_fingerprint(values) or not record["prefix"].startswith("m6ui_"):
        raise RuntimeError("Fixture ownership mismatch")
    return values, record


def prepare():
    values = guard()
    if FILE.exists():
        _, record = load()
        prefix = record["prefix"]
        suffix = prefix[5:]
    else:
        suffix = secrets.token_hex(4)
        prefix = "m6ui_" + suffix
        record = {"prefix": prefix, "targetFingerprint": target_fingerprint(values),
                  "password": secrets.token_urlsafe(24), "pin": str(secrets.randbelow(900000) + 100000),
                  "users": [], "products": [], "cardIds": []}
    def persist():
        FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        protect(FILE)
    persist()
    with database(values) as conn, httpx.Client(base_url="http://127.0.0.1:13000", trust_env=False, timeout=30) as client:
        for kind in ("browser", "api"):
            if any(user["kind"] == kind for user in record["users"]):
                continue
            username = prefix + "_" + kind
            request(client, "POST", "/api/auth/register", data={"userId": username, "password": record["password"]})
            uid = query(conn, "SELECT id FROM users WHERE user_id=%s", (username,))[0][0]
            record["users"].append({"username": username, "id": uid, "kind": kind})
            persist()
            token = request(client, "POST", "/api/auth/login", data={"userId": username, "password": record["password"]})["token"]
            request(client, "POST", "/api/auth/activate-wallet", token, {"password": record["pin"]})
            card = "M6" + secrets.token_hex(8)
            query(conn, "INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,100,0)", (card,))
            record["cardIds"].append(card)
            persist()
            request(client, "POST", "/api/wallet/recharge", token, {"cardId": card})
            request(client, "PUT", "/api/user/profile/details", token, {
                "basic": {"userId": username, "name": "合成智能收货人", "phoneNum": "13800138000", "address": "合成智能测试地址"},
                "health": {"aiProfileConsent": False}})
            request(client, "POST", "/api/auth/logout", token, {})
        for label in ("虚构智能枇杷露", "虚构智能布洛芬"):
            name = label + suffix
            if any(product["name"] == name for product in record["products"]):
                continue
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,2.50,30)", (name,))
                record["products"].append({"id": cursor.lastrowid, "name": name})
            persist()
    print('{"prepared":true,"syntheticUsers":2,"pendingSyntheticProducts":2,"secretsLogged":false}')


def verify():
    values, record = load()
    owner = next(row for row in record["users"] if row["kind"] == "api")
    product = record["products"][0]
    with httpx.Client(base_url="http://127.0.0.1:13000", trust_env=False, timeout=210) as client:
        token = request(client, "POST", "/api/auth/login", data={"userId": owner["username"], "password": record["password"]})["token"]
        policy = request(client, "GET", "/api/wallet/auto-order-policy", token)
        request(client, "PUT", "/api/wallet/auto-order-policy", token, {"enabled": True, "perOrderLimit": 50, "dailyLimit": 200,
                "expectedVersion": policy["version"], "password": record["pin"]})
        agent = request(client, "POST", "/api/auth/agent-token", token, {})["token"]
        conversation = request(client, "POST", "/ai/v1/conversations", agent, {"title": "M6 模型自动下单联调"}, 201)["id"]
        turn = str(uuid.uuid4())
        message = "帮我下单2件" + product["name"]
        request(client, "POST", "/api/auto-orders/turns", token, {"turnId": turn, "conversationId": conversation, "message": message})
        response = client.post(f"/ai/v1/conversations/{conversation}/messages", headers={"Authorization": "Bearer " + agent},
                               json={"requestId": turn, "message": message})
        if response.status_code != 200 or 'event: done' not in response.text:
            raise RuntimeError("Real model stream did not complete")
        proposals = []
        for frame in response.text.replace("\r\n", "\n").split("\n\n"):
            if frame.startswith("event: tool_result"):
                payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
                proposal = payload.get("result", {}).get("proposal")
                if proposal:
                    proposals.append(proposal)
        if len(proposals) != 1 or proposals[0]["items"][0]["quantity"] != 2:
            raise RuntimeError("Model did not produce an exact grounded proposal")
        if any(value in response.text for value in (record["pin"], record["password"], "合成智能测试地址", "13800138000")):
            raise RuntimeError("Private wallet/shipping data appeared in the model stream")
        body = {"items": [{"medicineId": item["id"], "quantity": item["quantity"]} for item in proposals[0]["items"]]}
        receipt = request(client, "POST", f"/api/auto-orders/turns/{turn}/execute", token, body)
        replay = request(client, "POST", f"/api/auto-orders/turns/{turn}/execute", token, body)
        if receipt["status"] != "PAID" or receipt != replay:
            raise RuntimeError("Settlement or idempotent replay failed")
        order = request(client, "GET", "/api/orders/" + receipt["orderId"], token)
        if order["recipientAddress"] != "合成智能测试地址" or order["paymentStatus"] != "PAID":
            raise RuntimeError("Java did not fill shipping or settle the order")
        with database(values) as conn:
            balance, points = query(conn, "SELECT balance,points FROM users WHERE id=%s", (owner["id"],))[0]
            if str(balance) != "95.00" or points != 5:
                raise RuntimeError("Wallet balance/points not reconciled")
        request(client, "POST", "/api/auth/logout", token, {})
    report = {"passed": True, "realModel": True, "realMySQL": True, "groundedQuantity": 2,
              "amount": "5.00", "singleDebitOnReplay": True, "shippingFilledByJava": True,
              "privateDataAbsentFromModelStream": True, "syntheticOnly": True}
    directory = ROOT / "docs/evidence/m6"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def cleanup():
    values, record = load()
    with database(values) as conn:
        for user in record["users"]:
            if not user["username"].startswith(record["prefix"] + "_") or query(conn, "SELECT id FROM users WHERE user_id=%s", (user["username"],)) != ((user["id"],),):
                raise RuntimeError("Owned user identity mismatch")
        conn.begin()
        try:
            for user in record["users"]:
                uid = user["id"]
                for table in ("auto_order_turns", "auto_order_policy_audit", "auto_order_policies", "payment_records", "payment_operation_requests", "payment_authorizations"):
                    query(conn, "DELETE FROM " + table + " WHERE user_id=%s", (uid,))
                query(conn, "DELETE i FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.user_id=%s", (uid,))
                query(conn, "DELETE FROM transactions WHERE user_id=%s", (uid,))
                query(conn, "DELETE FROM checkout_requests WHERE user_id=%s", (uid,))
                query(conn, "DELETE FROM orders WHERE user_id=%s", (uid,))
                query(conn, "DELETE i FROM order_draft_items i JOIN order_drafts d ON d.id=i.draft_id WHERE d.user_id=%s", (uid,))
                for table in ("order_drafts", "order_agent_grants", "profile_consent_events", "auth_sessions"):
                    query(conn, "DELETE FROM " + table + " WHERE user_id=%s", (uid,))
                for card in record["cardIds"]:
                    query(conn, "DELETE FROM recharge_cards WHERE id=%s AND used_by=%s", (card, uid))
                query(conn, "DELETE FROM security_attempts WHERE attempt_key IN (%s,%s)", ("login:" + user["username"], "pay:" + user["username"]))
                query(conn, "DELETE FROM users WHERE id=%s AND user_id=%s", (uid, user["username"]))
            for product in record["products"]:
                if not product["name"].endswith(record["prefix"][5:]):
                    raise RuntimeError("Owned product mismatch")
                query(conn, "DELETE FROM medicine_evidence WHERE medicine_id=%s", (product["id"],))
                query(conn, "DELETE FROM medicine_admin_audit WHERE medicine_id=%s", (product["id"],))
                query(conn, "DELETE FROM medicines WHERE id=%s AND name=%s", (product["id"], product["name"]))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    with sqlite3.connect(RUN / "conversations.db") as conn:
        for user in record["users"]:
            conn.execute("DELETE FROM turns WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)", (user["username"],))
            conn.execute("DELETE FROM conversations WHERE user_id=?", (user["username"],))
    FILE.unlink()
    print('{"cleaned":true,"syntheticOnly":true,"normalFundsChanged":false}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify", "cleanup"))
    {"prepare": prepare, "verify": verify, "cleanup": cleanup}[parser.parse_args().action]()
