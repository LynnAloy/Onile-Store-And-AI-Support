"""Owned synthetic payment UI fixtures. No normal schema or real merchandise is modified."""
import argparse
import json
import os

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from local_stack import RUN, database, query, protect, target_fingerprint
from m51_live_smoke import PaymentSmoke

FILE = RUN / "m51c-browser.json"


def prepare():
    guard()
    if FILE.exists():
        raise RuntimeError("Owned browser fixtures already exist; clean up before preparing again")
    smoke = PaymentSmoke()
    try:
        tokens = []
        for name, card in zip(smoke.names, [smoke.card, smoke.card_b]):
            smoke.request("POST", "/api/auth/register", data={"userId": name, "password": smoke.password})
            token = smoke.request("POST", "/api/auth/login", data={"userId": name, "password": smoke.password})["token"]
            tokens.append(token)
            smoke.request("POST", "/api/auth/activate-wallet", token, {"password": smoke.pin})
            query(smoke.conn, "INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)", (card,))
            smoke.request("POST", "/api/wallet/recharge", token, {"cardId": card})
        with smoke.conn.cursor() as cursor:
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,0.10,100)", (smoke.product_name,))
            smoke.product = cursor.lastrowid
        smoke.persist_fixture()
        smoke.qualify_fixture()
        drafts = {name: smoke.prepare(tokens[0], quantity) for name, quantity in (("normal", 5), ("close", 3), ("wrongPin", 2))}
        # Unpaid long list uses existing owned synthetic seed products without modifying their stock.
        products = query(smoke.conn, "SELECT id FROM medicines WHERE reference_source=%s AND review_status='APPROVED' AND sale_classification='OTC' AND stock>=1 ORDER BY id LIMIT 9",
                         ("local://synthetic-tests/m43",))
        intent = {"items": [{"medicineId": row[0], "quantity": 1} for row in products] + [{"medicineId": smoke.product, "quantity": 1}]}
        grant = smoke.request("POST", "/api/auth/order-agent-token", tokens[0], intent)
        response = smoke.http.post(smoke.java_base + "/internal/ai/v1/order-drafts", json=intent,
            headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": smoke.values["AI_SERVICE_KEY"], "Idempotency-Key": grant["requestKey"]})
        response.raise_for_status()
        did = response.json()["draftId"]
        smoke.request("POST", f"/api/order-drafts/{did}/confirm", tokens[0], {"version": 1,
            "recipientName": "合成测试用户", "recipientPhone": "13800138000", "recipientAddress": "虚构界面测试地址，仅用于本地合成数据"})
        long_order = smoke.checkout(tokens[0], did)["orderId"]
        # Leave a PREPARED draft for browser confirmation instead of bypassing that UI step.
        intent = {"items": [{"medicineId": smoke.product, "quantity": 4}]}
        grant = smoke.request("POST", "/api/auth/order-agent-token", tokens[0], intent)
        response = smoke.http.post(smoke.java_base + "/internal/ai/v1/order-drafts", json=intent,
            headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": smoke.values["AI_SERVICE_KEY"], "Idempotency-Key": grant["requestKey"]})
        response.raise_for_status()
        drafts["prepared"] = response.json()["draftId"]
        private = {"prefix": smoke.prefix, "targetFingerprint": target_fingerprint(smoke.values),
            "fixtureFile": str(smoke.fixture_path), "a": {"userId": smoke.names[0], "password": smoke.password},
            "b": {"userId": smoke.names[1], "password": smoke.password}, "pin": smoke.pin,
            "drafts": drafts, "longOrder": long_order, "longItemCount": len(intent["items"]), "product": smoke.product}
        private["longItemCount"] = len(products) + 1
        FILE.write_text(json.dumps(private, indent=2), encoding="utf-8")
        protect(FILE)
        smoke.http.close()
        smoke.conn.close()
        print(json.dumps({"prepared": True, "syntheticOnly": True, "drafts": len(drafts), "longItemCount": private["longItemCount"], "credentialsLogged": False}))
    except BaseException:
        smoke.cleanup()
        raise


def cleanup():
    values = guard()
    data = json.loads(FILE.read_text(encoding="utf-8"))
    if data["targetFingerprint"] != target_fingerprint(values):
        raise RuntimeError("Fixture target mismatch")
    from pathlib import Path
    fixture = Path(data["fixtureFile"]).resolve()
    if fixture.parent != (RUN / "fixtures").resolve() or fixture.stem != data["prefix"]:
        raise RuntimeError("Fixture ownership path mismatch")
    registry = json.loads(fixture.read_text(encoding="utf-8"))
    if registry["targetFingerprint"] != target_fingerprint(values) or registry["prefix"] != data["prefix"] or not data["prefix"].startswith("it_"):
        raise RuntimeError("Fixture owner mismatch")
    smoke = PaymentSmoke()
    with smoke.conn.cursor() as cursor:
        for row in registry["users"]:
            if not row["name"].startswith(data["prefix"] + "_"):
                raise RuntimeError("Synthetic user name is outside owned prefix")
            cursor.execute("SELECT id FROM users WHERE user_id=%s", (row["name"],))
            if cursor.fetchone() != (row["id"],):
                raise RuntimeError("Synthetic user identity changed")
    smoke.created_names = [row["name"] for row in registry["users"]]
    smoke.prefix = registry["prefix"]
    smoke.product, smoke.product_name = registry["product"], registry["productName"]
    smoke.card, smoke.card_b = registry["card"], registry["cardB"]
    smoke.fixture_path = fixture
    smoke.cleanup()
    ids = [row["id"] for row in registry["users"]]
    marks = ",".join(["%s"] * len(ids))
    with database(values) as conn:
        remaining = {table: query(conn, "SELECT COUNT(*) FROM " + table + " WHERE " + column + " IN (" + marks + ")", ids)[0][0]
            for table, column in (("users", "id"), ("orders", "user_id"), ("payment_records", "user_id"), ("payment_authorizations", "user_id"), ("payment_operation_requests", "user_id"))}
        remaining["ownedProduct"] = query(conn, "SELECT COUNT(*) FROM medicines WHERE id=%s AND name=%s", (registry["product"],registry["productName"]))[0][0]
    if any(remaining.values()):
        raise RuntimeError("Owned synthetic records remain after cleanup")
    FILE.unlink()
    report = {"cleaned": True, "syntheticOnly": True, "normalDatabaseChanged": False, "remainingOwnedRows": remaining}
    (RUN / "m51c-cleanup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


def fresh_draft():
    values = guard()
    data = json.loads(FILE.read_text(encoding="utf-8"))
    if data["targetFingerprint"] != target_fingerprint(values):
        raise RuntimeError("Fixture target mismatch")
    smoke = PaymentSmoke()
    try:
        product = query(smoke.conn, "SELECT id FROM medicines WHERE id=%s AND name=%s AND reference_source=%s",
            (data["product"], "联调专用商品_" + data["prefix"], "local://synthetic-tests/" + data["prefix"]))
        if len(product) != 1:
            raise RuntimeError("Owned fixture product changed")
        smoke.product = data["product"]
        token = smoke.request("POST", "/api/auth/login", data=data["a"])["token"]
        data["drafts"]["withdraw"] = smoke.prepare(token, 1)
        smoke.request("POST", "/api/auth/logout", token)
        FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(json.dumps({"freshOwnedDraft": True, "syntheticOnly": True}))
    finally:
        smoke.http.close()
        smoke.conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "cleanup", "fresh-draft"))
    args = parser.parse_args()
    {"prepare": prepare, "cleanup": cleanup, "fresh-draft": fresh_draft}[args.action]()
