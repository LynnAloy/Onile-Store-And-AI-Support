"""Loopback-only, demo-only response fault injection. No Java production fault endpoints."""
import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

os.environ["DEEPSEEKDOC_DEMO"] = "1"
import httpx
from demo import guard
import local_stack as stack

MARKER = "deepseekdoc-m51d-fault-proxy-v1"
PROOF = stack.RUN / "m51d-fault-proxy.json"
CONTROL = stack.RUN / "m51d-fault-control.json"
EVENTS = stack.RUN / "m51d-fault-events.jsonl"
LOCK = threading.Lock()
CLAIMED = set()
ISSUED = {}


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def event(kind, **data):
    with LOCK:
        with EVENTS.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": kind, "at": time.time(), **data}) + "\n")


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log headers, query credentials or request/response bodies.

    def send(self, status, body, headers=None):
        self.send_response(status)
        for key, value in (headers or {"Content-Type": "application/json", "Cache-Control": "no-store"}).items():
            if key.lower() not in {"connection", "transfer-encoding", "content-length", "content-encoding"}:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def forward(self):
        path = urlsplit(self.path).path
        if path == "/__fault_health" and self.command == "GET":
            proof = read(PROOF)
            self.send(200, json.dumps({k: proof[k] for k in ("marker", "runId", "targetFingerprint")}).encode())
            return
        if not path.startswith("/api/"):
            self.send(404, b'{}')
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            self.send(413, b'{}')
            return
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection", "content-length", "accept-encoding"}}
        digest = hashlib.sha256(self.headers.get("Authorization", "").encode()).hexdigest()
        if self.command == "DELETE" and path.endswith("/payment-authorizations"):
            aid = parse_qs(urlsplit(self.path).query).get("authorizationId", [None])[0]
            with LOCK:
                issued = ISSUED.get(aid)
            if issued:
                event("scoped_late_revoke", originalOwner=issued == digest, authorizationIdSpecified=True)
        barrier = None
        rule_before = read(CONTROL)
        if rule_before.get("mode") == "abort_before_settlement" and self.command == "POST" and path == "/api/orders/" + str(rule_before.get("orderId")) + "/pay":
            with LOCK:
                if rule_before["id"] not in CLAIMED:
                    CLAIMED.add(rule_before["id"])
                    barrier = abort_barrier(rule_before,self.headers.get("Idempotency-Key",""))
        try:
            with httpx.Client(trust_env=False, timeout=40) as client:
                result = client.request(self.command, "http://127.0.0.1:18080" + self.path, headers=headers, content=body)
        except httpx.HTTPError:
            event("upstream_unavailable", method=self.command)
            self.send(503, b'{"code":"UPSTREAM_UNAVAILABLE","message":"test upstream unavailable","outcome":"UNKNOWN"}')
            return
        finally:
            if barrier:
                connection,done = barrier
                done.wait(40)
                connection.rollback()
                connection.close()
                event("abort_barrier_released")
        rule = read(CONTROL)
        expected = "/api/orders/" + str(rule.get("orderId", ""))
        mode = rule.get("mode")
        if rule.get("id") in CLAIMED and result.status_code == 200 and (
            rule.get("releaseOn") == "login" and self.command == "POST" and path == "/api/auth/login"
            or rule.get("releaseOn") == "next_authorization" and self.command == "POST" and path == expected + "/payment-authorizations"):
            rule["release"] = True
            write(CONTROL, rule)
        matches = (mode == "drop_pay_response" and self.command == "POST" and path == expected + "/pay" and result.status_code == 200
            or mode == "delay_authorization" and self.command == "POST" and path == expected + "/payment-authorizations" and result.status_code == 200
            or mode == "delay_read_unauthorized" and self.command == "GET" and path == expected and result.status_code == 401)
        claimed = False
        with LOCK:
            if matches and rule.get("id") not in CLAIMED:
                CLAIMED.add(rule["id"])
                claimed = True
        if claimed:
            event("fault_applied", id=rule["id"], mode=mode, upstreamStatus=result.status_code)
            if mode == "drop_pay_response":
                event("committed_response_dropped", id=rule["id"], upstreamStatus=200)
                self.close_connection = True
                try: self.connection.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                self.connection.close()
                return
            if mode == "delay_authorization":
                with LOCK:
                    ISSUED[result.json()["authorizationId"]] = digest
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                current = read(CONTROL)
                if current.get("id") != rule["id"] or current.get("release"):
                    break
                time.sleep(0.1)
            event("delayed_response_released", id=rule["id"], upstreamStatus=result.status_code)
        event("forwarded", method=self.command, path=path, status=result.status_code)
        self.send(result.status_code, result.content, dict(result.headers))

    do_GET = do_POST = do_DELETE = do_PUT = do_OPTIONS = forward


def verified_pid(pid, required):
    if not isinstance(pid, int) or pid < 1:
        raise RuntimeError("Invalid owned process id")
    script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); " + f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
    command = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, encoding="utf-8", errors="replace")
    line = command.stdout.replace("\\", "/").lower()
    if command.returncode or not all(term.replace("\\", "/").lower() in line for term in required):
        raise RuntimeError("Process ownership could not be verified")
    return line


def start():
    values = guard()
    if PROOF.exists() or stack.listening(18181):
        raise RuntimeError("Fault proxy already exists or port occupied")
    write(PROOF, {"marker": MARKER, "runId": secrets.token_hex(16), "targetFingerprint": stack.target_fingerprint(values)})
    process = stack.launch("m51d-fault-proxy", [sys.executable, str(Path(__file__).resolve()), "serve"], stack.ROOT, os.environ.copy())
    record = read(PROOF)
    record["pid"] = process.pid
    write(PROOF, record)
    stack.wait_http(process, "http://127.0.0.1:18181/__fault_health")
    print(json.dumps({"started": True, "loopbackPort": 18181, "demoOnly": True}))


def stop():
    guard()
    record = read(PROOF)
    verified_pid(record.get("pid"), [str(Path(__file__).resolve()), "serve"])
    os.kill(record["pid"], signal.SIGTERM)
    PROOF.unlink()
    CONTROL.unlink(missing_ok=True)
    print(json.dumps({"stopped": True, "normalStackTouched": False}))


def arm(mode, order, release_on="manual"):
    values = guard()
    fixture = read(stack.RUN / "m51c-browser.json")
    if fixture.get("targetFingerprint") != stack.target_fingerprint(values):
        raise RuntimeError("Owned fixture target missing")
    with stack.database(values) as conn:
        owned = stack.query(conn, "SELECT o.id FROM orders o JOIN users u ON u.id=o.user_id WHERE o.id=%s AND u.user_id=%s", (order,fixture["a"]["userId"]))
        if len(owned) != 1 or not fixture["a"]["userId"].startswith(fixture["prefix"] + "_"):
            raise RuntimeError("Refusing fault injection into a non-owned order")
    write(CONTROL, {"id": secrets.token_hex(12), "orderId": order, "mode": mode, "release": False, "releaseOn": release_on})
    print(json.dumps({"armed": True, "mode": mode, "ownedSyntheticOnly": True}))


def stop_java():
    guard()
    state = read(stack.RUN / "stack.json")
    record = state.get("java", {})
    if record.get("environmentMarker") != "demo":
        raise RuntimeError("Not the demo Java process")
    line = verified_pid(record.get("pid"), [str(stack.ROOT), "java"])
    if "-ddeepseekdoc.environment=demo" not in line and str(stack.RUN / "java.args").replace("\\", "/").lower() not in line:
        raise RuntimeError("Refusing to stop Java without the demo environment marker")
    os.kill(record["pid"], signal.SIGTERM)
    deadline = time.monotonic() + 15
    while stack.listening(18080) and time.monotonic() < deadline:
        time.sleep(0.1)
    if stack.listening(18080): raise RuntimeError("Demo Java did not stop")
    write(stack.RUN / "m51d-java-stopped.json", {"marker": MARKER, "oldPid": record["pid"]})
    event("demo_java_stopped")
    print(json.dumps({"demoJavaStopped": True, "frontendKeptRunning": True}))


def abort_barrier(rule, key):
    values=guard()
    fixture=read(stack.RUN/"m51c-browser.json")
    holder=stack.database(values)
    rows=stack.query(holder,"SELECT o.user_id FROM orders o JOIN users u ON u.id=o.user_id JOIN order_items i ON i.order_id=o.id JOIN medicines m ON m.id=i.medicine_id WHERE o.id=%s AND u.user_id=%s AND m.id=%s AND m.reference_source=%s",
        (rule["orderId"],fixture["a"]["userId"],fixture["product"],"local://synthetic-tests/"+fixture["prefix"]))
    if len(rows)!=1: holder.close(); raise RuntimeError("Abort barrier is outside the owned fixture")
    user=rows[0][0]
    holder.begin()
    stack.query(holder,"SELECT stock FROM medicines WHERE id=%s FOR UPDATE",(fixture["product"],))
    done=threading.Event()
    def monitor():
        try:
            with stack.database(values) as db:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    request=stack.query(db,"SELECT status FROM payment_operation_requests WHERE user_id=%s AND operation='PAY' AND request_key=%s AND target_id=%s",(user,key,rule["orderId"]))
                    if request==(("REGISTERED",),):
                        db.begin()
                        try: stack.query(db,"SELECT id FROM users WHERE id=%s FOR UPDATE NOWAIT",(user,))
                        except stack.pymysql.err.OperationalError as exc:
                            db.rollback()
                            if exc.args[0]!=3572: raise
                            event("registered_transaction_waiting_on_owned_product",id=rule["id"])
                            stop_java()
                            event("abort_kill_completed",id=rule["id"])
                            return
                        db.rollback()
                    time.sleep(0.02)
            event("abort_monitor_not_triggered",id=rule["id"])
        finally: done.set()
    threading.Thread(target=monitor,daemon=True).start()
    return holder,done


def start_java():
    values = guard()
    stopped = read(stack.RUN / "m51d-java-stopped.json")
    if stopped.get("marker") != MARKER or stack.listening(18080):
        raise RuntimeError("No verified stopped Java instance")
    environment = os.environ.copy()
    environment.update(values)
    environment.update({"SERVER_ADDRESS":"127.0.0.1", "SERVER_PORT":"18080", "PAYMENTS_ENABLED":stack.payment_mode(values),
        "MIGRATE_LEGACY_PASSWORDS":"false", "ALLOWED_ORIGINS":"http://127.0.0.1:13000,http://localhost:13000",
        "DB_URL":"jdbc:mysql://" + values.get("DB_HOST","127.0.0.1") + ":" + values.get("DB_PORT","3306") + "/" + values["DB_NAME"]
            + "?useSSL=false&useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8"})
    for log in (stack.RUN / "logs").glob("java.*.log"):
        log.write_text("", encoding="utf-8")
    process = stack.launch("java", stack.java_command(), stack.JAVA, environment)
    stack.wait_java(process)
    state = read(stack.RUN / "stack.json")
    state["java"] = {"pid":process.pid, "environmentMarker":"demo"}
    write(stack.RUN / "stack.json", state)
    (stack.RUN / "m51d-java-stopped.json").unlink()
    event("demo_java_restarted")
    print(json.dumps({"demoJavaRestarted": True, "pidChanged": process.pid != stopped["oldPid"]}))


def hold_lock():
    values = guard()
    fixture = read(stack.RUN / "m51c-browser.json")
    proof = stack.RUN / "m51d-sql-lock.json"
    release = stack.RUN / "m51d-release-lock.flag"
    with stack.database(values) as conn:
        owned = stack.query(conn,"SELECT id FROM medicines WHERE id=%s AND reference_source=%s",(fixture["product"],"local://synthetic-tests/"+fixture["prefix"]))
        if len(owned)!=1: raise RuntimeError("Refusing a non-owned product lock")
        conn.begin()
        try:
            stack.query(conn,"SELECT stock FROM medicines WHERE id=%s FOR UPDATE",(fixture["product"],))
            write(proof,{"marker":MARKER,"pid":os.getpid(),"held":True,"connectionId":stack.query(conn,"SELECT CONNECTION_ID()")[0][0]})
            event("owned_product_lock_held")
            deadline=time.monotonic()+60
            while not release.exists() and time.monotonic()<deadline: time.sleep(0.1)
        finally:
            conn.rollback()
            proof.unlink(missing_ok=True)
            release.unlink(missing_ok=True)
            event("owned_product_lock_released")


def lock_start():
    guard()
    proof=stack.RUN/"m51d-sql-lock.json"
    if proof.exists(): raise RuntimeError("Owned lock is already held")
    (stack.RUN/"m51d-release-lock.flag").unlink(missing_ok=True)
    process=stack.launch("m51d-sql-lock",[sys.executable,str(Path(__file__).resolve()),"hold-lock"],stack.ROOT,os.environ.copy())
    deadline=time.monotonic()+10
    while not proof.exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(0.1)
    if not proof.exists(): raise RuntimeError("Owned product lock was not acquired")
    print('{"ownedProductLocked":true}')


def lock_release():
    (stack.RUN/"m51d-release-lock.flag").write_text("release",encoding="utf-8")
    deadline=time.monotonic()+5
    while (stack.RUN/"m51d-sql-lock.json").exists() and time.monotonic()<deadline: time.sleep(0.1)
    print(json.dumps({"released":not (stack.RUN/"m51d-sql-lock.json").exists()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start","serve","stop","arm","release","stop-java","start-java","lock-start","hold-lock","lock-release"))
    parser.add_argument("--mode", choices=("drop_pay_response","delay_authorization","delay_read_unauthorized","abort_before_settlement"))
    parser.add_argument("--order")
    parser.add_argument("--release-on", choices=("manual","login","next_authorization"), default="manual")
    args = parser.parse_args()
    if args.action == "serve":
        guard()
        ThreadingHTTPServer(("127.0.0.1",18181),Handler).serve_forever()
    elif args.action == "arm": arm(args.mode,args.order,args.release_on)
    elif args.action == "release":
        rule=read(CONTROL); rule["release"]=True; write(CONTROL,rule); print('{"released":true}')
    else: {"start":start,"stop":stop,"stop-java":stop_java,"start-java":start_java,"lock-start":lock_start,"hold-lock":hold_lock,"lock-release":lock_release}[args.action]()
