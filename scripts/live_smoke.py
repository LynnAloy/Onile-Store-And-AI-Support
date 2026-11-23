"""Real HTTP/MySQL/Ollama smoke checks. Only this run's fixtures are cleaned up."""
import json
import concurrent.futures
import secrets
import sqlite3
import sys
import time
import threading
import uuid

import httpx

from local_stack import ROOT, RUN, FRONT_PORT, JAVA_PORT, config, database, query, ensure_private, target_fingerprint


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


class Smoke:
    def __init__(self):
        self.values = config()
        self.base = f"http://127.0.0.1:{FRONT_PORT}"
        self.java_base = f"http://127.0.0.1:{JAVA_PORT}"
        self.http = httpx.Client(
            trust_env=False, timeout=httpx.Timeout(210, connect=5), headers={"Origin": self.base},
        )
        self.prefix = "it_" + time.strftime("%m%d%H%M%S") + "_" + secrets.token_hex(2)
        self.names = [self.prefix + "_a", self.prefix + "_b"]
        self.created_names = []
        self.password = secrets.token_urlsafe(18)
        self.pin = str(secrets.randbelow(900000) + 100000)
        self.card = "IT" + secrets.token_hex(8)
        self.card_b = "ITB" + secrets.token_hex(8)
        self.product_name = "联调专用商品_" + self.prefix
        self.product = None
        self.results = []
        self.conn = database(self.values)

    def record(self, name, **details):
        self.results.append({"check": name, "passed": True, **details})

    def persist_fixture(self):
        directory = RUN / "fixtures"
        directory.mkdir(exist_ok=True)
        self.fixture_path = directory / (self.prefix + ".json")
        users = [{"name": name, "id": query(self.conn, "SELECT id FROM users WHERE user_id=%s", (name,))[0][0]}
                 for name in self.created_names]
        data = {"targetFingerprint": target_fingerprint(self.values), "prefix": self.prefix,
                "users": users, "product": self.product, "productName": self.product_name,
                "card": self.card, "cardB": self.card_b}
        temporary = self.fixture_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self.fixture_path)

    def qualify_fixture(self):
        check(self.product_name.startswith("联调专用商品_" + self.prefix), "Only this run's synthetic product can be qualified")
        query(self.conn, "UPDATE medicines SET sale_classification='OTC',review_status='APPROVED',"
              "reference_source=%s,reviewed_by='synthetic-fixture',qualification_version=1 WHERE id=%s AND name=%s",
              ("local://synthetic-tests/" + self.prefix, self.product, self.product_name))

    def request(self, method, path, token=None, data=None, expected=200, headers=None):
        auth = {"Authorization": "Bearer " + token} if token else {}
        auth.update(headers or {})
        response = self.http.request(method, self.base + path, json=data, headers=auth)
        check(response.status_code == expected, path + " returned HTTP " + str(response.status_code))
        if method == "POST" and path == "/api/auth/register" and response.status_code == 200:
            if data and data.get("userId") in self.names:
                self.created_names.append(data["userId"])
                self.persist_fixture()
        if expected not in (200, 201) or not response.content:
            return None
        return response.json()

    def stream(self, conversation, token, message, request_id=None, cancel=False):
        rid = request_id or str(uuid.uuid4())
        started = time.monotonic()
        kinds, pieces, first_delta, replayed = [], [], None, False
        with self.http.stream(
            "POST", self.base + f"/ai/v1/conversations/{conversation}/messages",
            headers={"Authorization": "Bearer " + token},
            json={"requestId": rid, "message": message},
        ) as response:
            check(response.status_code == 200, "AI stream did not start")
            kind = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    item = json.loads(line[5:].strip())
                    kinds.append(kind)
                    if kind == "error":
                        raise RuntimeError("AI stream failed: " + item.get("code", "UNKNOWN"))
                    if kind == "start":
                        replayed = item.get("replayed", False)
                    if kind == "delta":
                        first_delta = first_delta or time.monotonic() - started
                        pieces.append(item["text"])
                        if cancel:
                            break
        check(first_delta is not None, "Model did not emit text")
        if not cancel:
            check(kinds[-1] == "done", "Stream ended without explicit completion")
        return {
            "requestId": rid, "answer": "".join(pieces), "replayed": replayed,
            "firstDeltaSeconds": round(first_delta, 2),
            "totalSeconds": round(time.monotonic() - started, 2),
        }

    def run(self):
        page = self.http.get(self.base + "/main")
        check(page.status_code == 200 and 'id="app"' in page.text, "Frontend route is unavailable")
        self.request("GET", "/ai/health")
        self.request("GET", "/api/user/profile", expected=401)
        self.record("Vue page, Vite proxy and anonymous access")

        users = []
        for name in self.names:
            self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
            users.append(self.request("POST", "/api/auth/login",
                                      data={"userId": name, "password": self.password}))
        a, b = users[0]["token"], users[1]["token"]
        self.request("GET", "/api/user/profile?userId=" + self.names[1], a, expected=403)
        self.request("GET", "/api/wallet/" + self.names[1], a, expected=403)
        self.request("PUT", "/api/user/profile", a,
                     {"nickname": "联调用户", "medicalHistory": ["仅用于联调的占位记录"]})
        profile = self.request("GET", "/api/user/profile", a)
        check(profile.get("medicalHistory") == ["仅用于联调的占位记录"], "MySQL JSON profile round-trip failed")
        self.record("Real MySQL registration/login, JSON profile and user ownership")

        for token in (a, b):
            self.request("POST", "/api/auth/activate-wallet", token, {"password": self.pin})
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)", (self.card,))
            cursor.execute("INSERT INTO medicines(name,price,stock) VALUES (%s,0.10,2)", (self.product_name,))
            self.product = cursor.lastrowid
        self.persist_fixture()
        self.qualify_fixture()
        self.request("POST", "/api/wallet/recharge", a, {"cardId": self.card})
        self.request("POST", "/api/wallet/recharge", b, {"cardId": self.card}, expected=400)
        self.request("PUT", f"/api/medicines/{self.product}/stock?quantity=100", a, expected=403)
        order = {
            "recipientName": "联调用户", "recipientPhone": "13800138000",
            "recipientAddress": "仅用于本地联调的虚构地址", "walletPassword": "000000",
            "items": [{"medicineId": self.product, "quantity": 1}],
        }
        key = str(uuid.uuid4())
        self.request("POST", "/api/orders", a, order, expected=401, headers={"Idempotency-Key": key})
        order["walletPassword"] = self.pin
        paid = self.request("POST", "/api/orders", a, order, headers={"Idempotency-Key": key})
        repeated = self.request("POST", "/api/orders", a, order, headers={"Idempotency-Key": key})
        check(paid["orderId"] == repeated["orderId"], "Checkout retry was not idempotent")
        check(str(paid["newBalance"]) == "49.9" or float(paid["newBalance"]) == 49.9, "Balance mismatch")
        self.request("GET", "/api/orders/" + paid["orderId"], b, expected=404)
        stock = query(self.conn, "SELECT stock FROM medicines WHERE id=%s", (self.product,))[0][0]
        check(stock == 1, "Idempotent retry changed inventory twice")
        self.record("Actual wallet PIN, checkout, idempotence and order isolation")

        query(self.conn, "INSERT INTO recharge_cards(id,amount,is_used) VALUES (%s,50,0)", (self.card_b,))
        self.request("POST", "/api/wallet/recharge", b, {"cardId": self.card_b})
        barrier = threading.Barrier(2)

        def purchase_last(token):
            barrier.wait(timeout=5)
            response = self.http.post(
                self.base + "/api/orders", json=order,
                headers={"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid.uuid4())},
            )
            return response.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            tasks = [executor.submit(purchase_last, token) for token in (a, b)]
            statuses = sorted(task.result(timeout=30) for task in tasks)
        check(statuses == [200, 400], "Last-item concurrent purchases did not have exactly one winner")
        check(query(self.conn, "SELECT stock FROM medicines WHERE id=%s", (self.product,))[0][0] == 0,
              "Last-item concurrent inventory mismatch")
        total = query(self.conn, "SELECT SUM(balance) FROM users WHERE user_id IN (%s,%s)", self.names)[0][0]
        check(str(total) == "99.80", "Concurrent purchase debited an incorrect combined balance")
        self.record("Real MySQL concurrent last-item purchase has one winner and one debit")

        grants = [self.request("POST", "/api/auth/agent-token", token) for token in (a, b)]
        agent_a, agent_b = grants[0]["token"], grants[1]["token"]
        self.request("GET", "/ai/v1/conversations", a, expected=401)
        response = self.http.get(
            self.java_base + "/internal/ai/v1/me",
            headers={"Authorization": "Bearer " + agent_a},
        )
        check(response.status_code == 401, "Java internal endpoint accepted a missing service key")
        response = self.http.get(
            self.java_base + "/internal/ai/v1/me",
            headers={"Authorization": "Bearer " + agent_a, "X-AI-Service-Key": self.values["AI_SERVICE_KEY"]},
        )
        check(response.status_code == 200, "Java delegated identity contract failed")
        conversation = self.request(
            "POST", "/ai/v1/conversations", agent_a, {"title": "真实环境联调"}, expected=201,
        )["id"]
        self.request("GET", f"/ai/v1/conversations/{conversation}/messages", agent_b, expected=404)
        self.record("Java-Python real delegation and conversation ownership")

        marker = "TEST" + str(secrets.randbelow(9000) + 1000)
        first = "本次项目测试代号是" + marker + "。请记住它，本轮只回复已记住。"
        result = self.stream(conversation, agent_a, first)
        replay = self.stream(conversation, agent_a, first, result["requestId"])
        check(replay["replayed"] and replay["answer"] == result["answer"], "AI idempotent replay failed")
        recall = self.stream(conversation, agent_a, "上一轮的项目测试代号是什么？只输出代号。")
        history = self.request("GET", f"/ai/v1/conversations/{conversation}/messages", agent_a)
        if marker not in recall["answer"]:
            diagnostic = {"syntheticMarker": marker, "firstAnswer": result["answer"],
                          "recallAnswer": recall["answer"],
                          "storedPrompts": [turn["message"] for turn in history["turns"]]}
            (RUN / "model-recall-failure.json").write_text(
                json.dumps(diagnostic, ensure_ascii=True, indent=2), encoding="utf-8",
            )
        check(marker in recall["answer"], "Real model failed the multi-turn context check")
        check(len(history["turns"]) == 2 and all(t["status"] == "completed" for t in history["turns"]),
              "History or replay persistence mismatch")
        self.record("Real Ollama streaming, multi-turn context, persistence and replay",
                    model=self.values.get("OLLAMA_MODEL"), firstDeltaSeconds=result["firstDeltaSeconds"],
                    firstTotalSeconds=result["totalSeconds"], secondTotalSeconds=recall["totalSeconds"])

        cancelled = self.stream(
            conversation, agent_a, "请从1开始逐行列出整数，一直列到1000。不要解释，不要省略。",
            cancel=True,
        )
        deadline = time.monotonic() + 25
        last = None
        while time.monotonic() < deadline:
            history = self.request("GET", f"/ai/v1/conversations/{conversation}/messages", agent_a)
            last = next(t for t in history["turns"] if t["requestId"] == cancelled["requestId"])
            if last["status"] != "processing":
                break
            time.sleep(0.5)
        check(last is not None and last["status"] == "interrupted", "Cancel did not interrupt upstream generation")
        self.record("Real proxy/client disconnect cancels model and records interruption")

        self.request("POST", "/api/auth/logout", a)
        self.request("GET", "/api/user/profile", a, expected=401)
        self.request("GET", "/ai/v1/conversations", agent_a, expected=401)
        self.request("GET", "/api/user/profile", b)
        self.record("Real logout revokes parent and AI delegation without affecting another user")

    def cleanup(self):
        names = self.created_names
        ids = [row[0] for row in query(
            self.conn, "SELECT id FROM users WHERE user_id IN (" + ",".join(["%s"] * len(names)) + ")", tuple(names),
        )] if names else []
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            payment_tables = bool(query(self.conn, "SHOW TABLES LIKE 'payment_records'"))
            self.conn.begin()
            try:
                with self.conn.cursor() as cursor:
                    if payment_tables:
                        for table in ("payment_records", "payment_operation_requests", "payment_authorizations"):
                            cursor.execute("DELETE FROM " + table + " WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM order_agent_grants WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM profile_consent_events WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM checkout_requests WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM order_items WHERE order_id IN "
                                   "(SELECT id FROM orders WHERE user_id IN (" + placeholders + "))", ids)
                    cursor.execute("DELETE FROM transactions WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM orders WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM order_draft_items WHERE draft_id IN "
                                   "(SELECT id FROM order_drafts WHERE user_id IN (" + placeholders + "))", ids)
                    cursor.execute("DELETE FROM order_drafts WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM auth_sessions WHERE user_id IN (" + placeholders + ")", ids)
                    cursor.execute("DELETE FROM recharge_cards WHERE id IN (%s,%s)", (self.card, self.card_b))
                    for name in names:
                        cursor.execute("DELETE FROM security_attempts WHERE attempt_key IN (%s,%s)",
                                       ("login:" + name, "pay:" + name))
                    cursor.execute("DELETE FROM users WHERE id IN (" + placeholders + ")", ids)
                    if self.product:
                        cursor.execute("DELETE FROM medicines WHERE id=%s AND name=%s",
                                       (self.product, self.product_name))
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
        ai_database = RUN / "conversations.db"
        if ai_database.exists() and names:
            with sqlite3.connect(ai_database) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                owned = ",".join(["?"] * len(names))
                conn.execute("DELETE FROM turns WHERE conversation_id IN "
                             "(SELECT id FROM conversations WHERE user_id IN (" + owned + "))", names)
                conn.execute("DELETE FROM conversations WHERE user_id IN (" + owned + ")", names)
        self.http.close()
        self.conn.close()
        if getattr(self, "fixture_path", None):
            self.fixture_path.unlink(missing_ok=True)


def main():
    ensure_private()
    smoke = Smoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception:
            failure = (failure or "") + " Scoped fixture cleanup failed; inspect local run data"
    report = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"), "realServices": True,
        "checks": smoke.results, "passed": failure is None, "failure": failure,
        "testCredentialsLogged": False,
    }
    (RUN / "live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
