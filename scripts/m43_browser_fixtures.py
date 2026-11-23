"""Synthetic UI failure fixtures; preparation uses real Java APIs, changes stay in the demo schema."""
import json
import os
import secrets

os.environ["DEEPSEEKDOC_DEMO"] = "1"
import httpx
from demo import guard
from local_stack import RUN, database, query


def main():
    values = guard()
    account = json.loads((RUN / "browser-account.json").read_text(encoding="utf-8"))
    rows = {}
    with database(values) as conn, httpx.Client(trust_env=False, timeout=15) as client:
        base = "http://127.0.0.1:13000"
        token = client.post(base + "/api/auth/login", json=account).json()["token"]
        auth = {"Authorization": "Bearer " + token}
        for kind, name in (("price", "虚构边界甲"), ("stock", "虚构边界乙"),
                           ("qualification", "虚构边界丙"), ("expiry", "虚构演示甲")):
            product = query(conn, "SELECT id FROM medicines WHERE name=%s AND reference_source=%s",
                            (name, "local://synthetic-tests/m43"))
            if len(product) != 1:
                raise RuntimeError("Synthetic fixture product ownership mismatch")
            pid = product[0][0]
            if kind != "expiry":
                query(conn, "UPDATE medicines SET price=1.25,stock=50,qualification_version=1 WHERE id=%s", (pid,))
            intent = {"items": [{"medicineId": pid, "quantity": 2}]}
            response = client.post(base + "/api/auth/order-agent-token", headers=auth, json=intent)
            response.raise_for_status()
            grant = response.json()
            response = client.post("http://127.0.0.1:18080/internal/ai/v1/order-drafts", json=intent,
                headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": values["AI_SERVICE_KEY"],
                         "Idempotency-Key": grant["requestKey"]})
            response.raise_for_status()
            did = response.json()["draftId"]
            if kind == "expiry":
                query(conn, "UPDATE order_drafts SET expires_at=0 WHERE id=%s", (did,))
            elif kind == "price":
                query(conn, "UPDATE medicines SET price=1.75 WHERE id=%s", (pid,))
            elif kind == "stock":
                query(conn, "UPDATE medicines SET stock=0 WHERE id=%s", (pid,))
            else:
                query(conn, "UPDATE medicines SET qualification_version=2 WHERE id=%s", (pid,))
            rows[kind] = did
        client.post(base + "/api/auth/logout", headers=auth).raise_for_status()
        path = RUN / "browser-alt-account.json"
        alternate = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "userId": "m43_browser_b", "password": secrets.token_urlsafe(18)}
        response = client.post(base + "/api/auth/register", json=alternate)
        if response.status_code not in (200, 409):
            raise RuntimeError("Alternate synthetic account registration failed")
        path.write_text(json.dumps(alternate), encoding="utf-8")
    (RUN / "browser-boundary-fixtures.json").write_text(json.dumps(rows), encoding="utf-8")
    print(json.dumps({"syntheticBoundaryDrafts": len(rows), "paid": False}))


if __name__ == "__main__":
    main()
