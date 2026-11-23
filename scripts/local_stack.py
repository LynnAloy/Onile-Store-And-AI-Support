"""Operate only this project's local integration stack; never print credentials."""
import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
import pymysql
from pymysql.constants import CLIENT

ROOT = Path(__file__).resolve().parent.parent
DEMO = os.getenv("DEEPSEEKDOC_DEMO") == "1"
RUN = ROOT / (".local-demo" if DEMO else ".local-run")
JAVA = ROOT / "mybatis-plus-demo" / "mybatis-plus-demo"
CONFIG = ROOT / (".env.demo.local" if DEMO else ".env.local")
JAVA_PORT, AI_PORT, FRONT_PORT = (18080, 18000, 13000) if DEMO else (8080, 8000, 3000)
MYSQL_BIN = Path(os.getenv("MYSQL_BIN", "D:/MySql/bin"))


def config():
    values = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    for key in values:
        if os.getenv(key):
            values[key] = os.environ[key]
    if DEMO and values.get("DB_NAME") != "DeepseekDoc_M43_Demo":
        raise RuntimeError("Demo mode requires the dedicated DeepseekDoc_M43_Demo database")
    return values


def database(values):
    if not values.get("DB_USERNAME") or not values.get("DB_PASSWORD"):
        raise RuntimeError("Fill DB_USERNAME and DB_PASSWORD in the ignored .env.local first")
    name = values.get("DB_NAME", "DeepSeekDoc")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError("DB_NAME contains unsupported characters")
    try:
        return pymysql.connect(
            host=values.get("DB_HOST", "127.0.0.1"), port=int(values.get("DB_PORT", "3306")),
            user=values["DB_USERNAME"], password=values["DB_PASSWORD"], database=name,
            charset="utf8mb4", autocommit=True, connect_timeout=5,
            client_flag=CLIENT.MULTI_STATEMENTS,
        )
    except pymysql.MySQLError as exc:
        raise RuntimeError(f"MySQL connection failed (code {exc.args[0]}); credentials were not logged") from None


def target_fingerprint(values):
    identity = "|".join(values.get(key, default) for key, default in (
        ("DB_HOST", "127.0.0.1"), ("DB_PORT", "3306"), ("DB_NAME", "DeepSeekDoc"), ("DB_USERNAME", ""),
    ))
    return hashlib.sha256(identity.encode()).hexdigest()


def initialize():
    ensure_private()
    values = config()
    if not values.get("DB_USERNAME") or not values.get("DB_PASSWORD"):
        raise RuntimeError("Fill database credentials first")
    name = values.get("DB_NAME", "DeepSeekDoc")
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise RuntimeError("DB_NAME contains unsupported characters")
    conn = pymysql.connect(
        host=values.get("DB_HOST", "127.0.0.1"), port=int(values.get("DB_PORT", "3306")),
        user=values["DB_USERNAME"], password=values["DB_PASSWORD"], charset="utf8mb4",
        autocommit=True, connect_timeout=5, client_flag=CLIENT.MULTI_STATEMENTS,
    )
    with conn:
        exists = query(conn, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                       "WHERE SCHEMA_NAME=%s", (name,))
        if exists:
            raise RuntimeError("Target database already exists; initialization refuses to overwrite it")
        query(conn, "CREATE DATABASE \u0060" + name
              + "\u0060 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        conn.select_db(name)
        script = (JAVA / "src/main/resources/sql/bootstrap-project.sql").read_text(encoding="utf-8")
        with conn.cursor() as cursor:
            cursor.execute(script)
            while cursor.nextset():
                pass
        result = {"database": name, "initialized": True, "usersImported": 0, "ordersImported": 0,
                  "catalogRows": query(conn, "SELECT COUNT(*) FROM medicines")[0][0]}
    (RUN / "initialized.json").write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(result))


def query(conn, sql, parameters=None):
    with conn.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()


def protect(path, directory=False):
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    account = os.environ["USERDOMAIN"] + "\\" + os.environ["USERNAME"]
    rights = "(OI)(CI)F" if directory else "F"
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r",
         account + ":" + rights, "SYSTEM:" + rights], capture_output=True,
    )
    if result.returncode:
        raise RuntimeError("Could not restrict access to local credentials/backups")


def ensure_private():
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    (RUN / "backups").mkdir(parents=True, exist_ok=True)
    protect(RUN, directory=True)
    if CONFIG.exists():
        protect(CONFIG)


def backup(values):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = RUN / "backups" / (
        values.get("DB_NAME", "DeepSeekDoc") + "-" + stamp + "-" + secrets.token_hex(3) + ".sql"
    )
    temporary = RUN / "mysql-client.cnf"

    def quote(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    text = "[client]\n" + "\n".join([
        "host=" + quote(values.get("DB_HOST", "127.0.0.1")),
        "port=" + values.get("DB_PORT", "3306"),
        "user=" + quote(values["DB_USERNAME"]),
        "password=" + quote(values["DB_PASSWORD"]),
    ]) + "\n"
    temporary.write_text(text, encoding="utf-8")
    protect(temporary)
    try:
        result = subprocess.run([
            str(MYSQL_BIN / "mysqldump.exe"), "--defaults-extra-file=" + str(temporary),
            "--single-transaction", "--routines", "--events", "--triggers",
            "--no-tablespaces", "--set-gtid-purged=OFF", "--column-statistics=0",
            "--default-character-set=utf8mb4", "--result-file=" + str(destination),
            values.get("DB_NAME", "DeepSeekDoc"),
        ], capture_output=True, timeout=120)
        if result.returncode or not destination.exists() or destination.stat().st_size < 100:
            raise RuntimeError("Database backup failed; migration was not attempted")
        protect(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def prepare():
    ensure_private()
    values = config()
    with database(values) as conn:
        tables = {row[0] for row in query(conn, "SHOW TABLES")}
        if not {"users", "orders", "order_items", "medicines", "transactions", "recharge_cards"} <= tables:
            raise RuntimeError("Target database does not match the project's business schema")
        columns = dict(query(conn, "SELECT COLUMN_NAME,CHARACTER_MAXIMUM_LENGTH "
                             "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
                             "AND TABLE_NAME='users'"))
        if "password" not in columns or "walletPassword" not in columns:
            raise RuntimeError("Unexpected user credential columns; refusing automatic changes")
        before = query(conn, "SELECT (SELECT COUNT(*) FROM users),(SELECT COUNT(*) FROM orders)")[0]
        destination = backup(values)
        needs_ddl = (
            columns["password"] < 255 or columns["walletPassword"] < 255
            or not {"auth_sessions", "security_attempts", "checkout_requests"} <= tables
        )
        if needs_ddl:
            sql = (JAVA / "src/main/resources/sql/migrations/V001_m1_security.sql").read_text(encoding="utf-8")
            with conn.cursor() as cursor:
                cursor.execute(sql)
                while cursor.nextset():
                    pass
        profile_columns = {
            "height_cm": "DECIMAL(4,1) NULL", "weight_kg": "DECIMAL(4,1) NULL",
            "medical_history_text": "TEXT NULL", "allergies_text": "TEXT NULL",
            "medications_text": "TEXT NULL", "lifestyle_text": "TEXT NULL", "health_notes": "TEXT NULL",
            "ai_profile_consent": "BOOLEAN NOT NULL DEFAULT FALSE",
            "profile_context_version": "BIGINT NOT NULL DEFAULT 0",
            "profile_consent_updated_at": "BIGINT NOT NULL DEFAULT 0",
        }
        profile_migrated = False
        for column, declaration in profile_columns.items():
            if column not in columns:
                query(conn, "ALTER TABLE users ADD COLUMN " + column + " " + declaration)
                profile_migrated = True
        query(conn, (JAVA / "src/main/resources/sql/m3-profile-schema.sql").read_text(encoding="utf-8"))
        medicine_columns = {row[0] for row in query(conn, "SHOW COLUMNS FROM medicines")}
        qualification_columns = {
            "sale_classification": "VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN'",
            "review_status": "VARCHAR(16) NOT NULL DEFAULT 'PENDING'",
            "reference_source": "VARCHAR(255) NULL", "reviewed_by": "VARCHAR(100) NULL",
            "qualification_version": "BIGINT NOT NULL DEFAULT 0",
        }
        for column, declaration in qualification_columns.items():
            if column not in medicine_columns:
                query(conn, "ALTER TABLE medicines ADD COLUMN " + column + " " + declaration)
        with conn.cursor() as cursor:
            cursor.execute((JAVA / "src/main/resources/sql/m4-draft-schema.sql").read_text(encoding="utf-8"))
            while cursor.nextset():
                pass
        legacy = query(conn, "SELECT COUNT(*) FROM users WHERE "
                       "password NOT REGEXP '^[$]2[aby][$]' OR "
                       "(walletPassword IS NOT NULL AND walletPassword NOT REGEXP '^[$]2[aby][$]')")[0][0]
        result = {
            "database": values.get("DB_NAME", "DeepSeekDoc"), "backup": str(destination),
            "usersBefore": before[0], "ordersBefore": before[1],
            "schemaMigrated": needs_ddl, "legacyAccounts": legacy,
            "profileSchemaMigrated": profile_migrated,
            "targetFingerprint": target_fingerprint(values),
        }
    (RUN / "prepared.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def check_model(values):
    requested = values.get("OLLAMA_MODEL", "Qwen2.5:latest")
    if ":" not in requested:
        requested += ":latest"
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            response = client.get("http://127.0.0.1:11434/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            matches = [item["name"] for item in models
                       if item.get("name", "").casefold() == requested.casefold()]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise RuntimeError("Ollama is unavailable; start the local model service first") from None
    if not matches:
        raise RuntimeError("Configured model is not available in the running Ollama model directory")
    return matches[0]


def java_command():
    java_home = os.getenv("JAVA_HOME")
    executable = Path(java_home) / "bin/java.exe" if java_home else None
    java_binary = str(executable) if executable and executable.exists() else "java"
    jar = JAVA / "target/mybatis-plus-demo-1.0.0.jar"
    if jar.exists():
        with zipfile.ZipFile(jar) as archive:
            executable = any(item.startswith("BOOT-INF/classes/") for item in archive.namelist())
        if executable:
            marker = "demo" if DEMO else "normal"
            return [java_binary, "-Dfile.encoding=UTF-8", "-Ddeepseekdoc.environment=" + marker, "-jar", str(jar)]
    # Offline fallback reuses the exact dependency set from the successful M2 Maven test build.
    report = JAVA / "target/surefire-reports/TEST-com.example.mybatisplus.M1SecurityBusinessTests.xml"
    properties = ET.parse(report).getroot().find("properties")
    classpath = next(item.attrib["value"] for item in properties
                     if item.attrib.get("name") == "java.class.path")
    entries = [item for item in classpath.split(os.pathsep)
               if "test-classes" not in item and not re.search(r"[/\\]h2[/\\]", item)]
    if not entries or any(not Path(item).exists() for item in entries):
        raise RuntimeError("Build Java with Maven first; cached runtime classpath is unavailable")
    args = RUN / "java.args"
    normalized = os.pathsep.join(item.replace("\\", "/") for item in entries)
    args.write_text('-Dfile.encoding=UTF-8\n-cp\n"' + normalized
                    + '"\ncom.example.mybatisplus.MybatisPlusDemoApplication\n', encoding="utf-8")
    return [java_binary, "@" + str(args)]


def launch(name, command, cwd, environment):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (RUN / "logs" / (name + ".stdout.log")).open("ab") as out:
        with (RUN / "logs" / (name + ".stderr.log")).open("ab") as err:
            process = subprocess.Popen(
                command, cwd=cwd, env=environment, stdout=out, stderr=err, creationflags=flags,
            )
    return process


def wait_java(process):
    deadline = time.monotonic() + 90
    log = RUN / "logs/java.stdout.log"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Java failed to start; inspect .local-run/logs/java.stdout.log")
        if log.exists() and "LOCAL_BACKEND_READY" in log.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(0.5)
    raise RuntimeError("Java startup timeout; inspect local logs")


def wait_http(process, url):
    deadline = time.monotonic() + 45
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Service exited before becoming ready: " + url)
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError("Service readiness timeout: " + url)


def payment_schema_fingerprint(values):
    with database(values) as conn:
        definitions = [re.sub(r"AUTO_INCREMENT=\d+", "AUTO_INCREMENT=<sequence>", query(conn,
            "SHOW CREATE TABLE `" + table + "`")[0][1]) for table in (
                "orders", "order_items", "payment_authorizations", "payment_records", "payment_operation_requests")]
    return hashlib.sha256("\n".join(definitions).encode()).hexdigest()


def payment_mode(values):
    if (RUN / "m6-migration.json").exists():
        return commerce_mode(values)
    if not DEMO or not (RUN / "m51-migration.json").exists():
        return "false"
    migration = json.loads((RUN / "m51-migration.json").read_text(encoding="utf-8"))
    schema_hash = hashlib.sha256((ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest()
    if not migration.get("passed") or migration.get("targetFingerprint") != target_fingerprint(values) \
            or migration.get("schemaSha256") != schema_hash:
        raise RuntimeError("Payment migration proof is stale; rerun the guarded demo migration")
    if migration.get("databaseStructureSha256") != payment_schema_fingerprint(values):
        raise RuntimeError("Payment schema drift detected; inspect before starting")
    return "true"


def commerce_schema_fingerprint(values):
    with database(values) as conn:
        definitions = [query(conn, "SHOW CREATE TABLE `" + table + "`")[0][1] for table in (
            "account_roles", "medicine_admin_audit", "auto_order_policies", "auto_order_policy_audit", "auto_order_turns")]
    return hashlib.sha256("\n".join(definitions).encode()).hexdigest()


def commerce_mode(values):
    path = RUN / "m6-migration.json"
    if not path.exists():
        return "false"
    proof = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "targetFingerprint": target_fingerprint(values),
        "schemaSha256": hashlib.sha256((ROOT / "docs/sql/M6-commerce.sql").read_bytes()).hexdigest(),
        "paymentSchemaSha256": hashlib.sha256((ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest(),
    }
    if not proof.get("passed") or any(proof.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Commerce migration evidence or schema drifted; inspect before starting")
    if proof.get("paymentStructureSha256") != payment_schema_fingerprint(values) \
            or proof.get("commerceStructureSha256") != commerce_schema_fingerprint(values):
        raise RuntimeError("Commerce database structure drifted; inspect before starting")
    return "true"


def evidence_mode(values):
    path = RUN / "p1-evidence-migration.json"
    if not path.exists():
        return "false"
    proof = json.loads(path.read_text(encoding="utf-8"))
    if not proof.get("passed") or proof.get("targetFingerprint") != target_fingerprint(values) or proof.get("schemaSha256") != hashlib.sha256((ROOT / "docs/sql/P1-evidence.sql").read_bytes()).hexdigest():
        raise RuntimeError("Evidence migration proof mismatch")
    with database(values) as conn:
        actual = hashlib.sha256(query(conn,"SHOW CREATE TABLE medicine_evidence")[0][1].encode()).hexdigest()
    if actual != proof.get("structureSha256"):
        raise RuntimeError("Evidence schema drift")
    return "true"


def frontend_java_target(values):
    direct = f"http://127.0.0.1:{JAVA_PORT}"
    proof = RUN / "m51d-fault-proxy.json"
    if not DEMO or not proof.exists():
        return direct
    record = json.loads(proof.read_text(encoding="utf-8"))
    if record.get("marker") != "deepseekdoc-m51d-fault-proxy-v1" or record.get("targetFingerprint") != target_fingerprint(values):
        raise RuntimeError("Fault proxy proof does not match the owned demo")
    with httpx.Client(trust_env=False, timeout=3) as client:
        health = client.get("http://127.0.0.1:18181/__fault_health").json()
    if health.get("marker") != record["marker"] or health.get("runId") != record.get("runId"):
        raise RuntimeError("Owned fault proxy is unavailable; refusing proxy redirection")
    return "http://127.0.0.1:18181"


def start():
    ensure_private()
    values = config()
    payments = payment_mode(values)
    commerce = commerce_mode(values)
    if not (RUN / "prepared.json").exists():
        raise RuntimeError("Run prepare first to back up and check the real database")
    prepared = json.loads((RUN / "prepared.json").read_text(encoding="utf-8"))
    if prepared.get("targetFingerprint") != target_fingerprint(values):
        raise RuntimeError("Database target changed since backup; run prepare again")
    with database(values) as conn:
        legacy = query(conn, "SELECT COUNT(*) FROM users WHERE "
                       "password NOT REGEXP '^[$]2[aby][$]' OR "
                       "(walletPassword IS NOT NULL AND walletPassword NOT REGEXP '^[$]2[aby][$]')")[0][0]
    selected_model = check_model(values)
    for port in (JAVA_PORT, AI_PORT, FRONT_PORT):
        if listening(port):
            raise RuntimeError(f"Port {port} is occupied; no existing process was stopped")
    key = values.get("AI_SERVICE_KEY")
    if not key:
        key = secrets.token_urlsafe(48)
        with CONFIG.open("a", encoding="utf-8") as file:
            file.write("\nAI_SERVICE_KEY=" + key + "\n")
        protect(CONFIG)
    if len(key) < 32:
        raise RuntimeError("AI_SERVICE_KEY must be at least 32 characters")
    environment = os.environ.copy()
    environment.update(values)
    environment.update({
        "AI_SERVICE_KEY": key, "DB_URL": "jdbc:mysql://" + values.get("DB_HOST", "127.0.0.1")
        + ":" + values.get("DB_PORT", "3306") + "/" + values.get("DB_NAME", "DeepSeekDoc")
        + "?useSSL=false&useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8",
        "JAVA_BASE_URL": f"http://127.0.0.1:{JAVA_PORT}", "SERVER_ADDRESS": "127.0.0.1",
        "SERVER_PORT": str(JAVA_PORT), "ALLOWED_ORIGINS": (
            "http://localhost:13000,http://127.0.0.1:13000" if DEMO else values.get(
                "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")),
        "OLLAMA_MODEL": selected_model,
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434", "MODEL_READ_TIMEOUT_SECONDS": "60",
        "MODEL_TIMEOUT_SECONDS": "180", "AI_DATABASE_PATH": str(RUN / "conversations.db"),
        "MODEL_TEMPERATURE": values.get("MODEL_TEMPERATURE", "0"),
        "KNOWLEDGE_DATABASE_PATH": str(RUN / "knowledge.db"),
        "EMBEDDING_MODEL": values.get("EMBEDDING_MODEL", "bge-m3:latest"),
        "MIGRATE_LEGACY_PASSWORDS": "true" if legacy else "false",
        "PAYMENTS_ENABLED": payments,
        "COMMERCE_ENABLED": commerce,
        "MEDICINE_EVIDENCE_ENABLED": evidence_mode(values),
        "AI_CONFIG_PATH": str(RUN / "model-config.json"),
    })
    launched = {}
    try:
        for log in (RUN / "logs").glob("java.*.log"):
            log.write_text("", encoding="utf-8")
        process = launch("java", java_command(), JAVA, environment)
        launched["java"] = process
        wait_java(process)
        if legacy:
            process.terminate()
            process.wait(timeout=15)
            environment["MIGRATE_LEGACY_PASSWORDS"] = "false"
            for log in (RUN / "logs").glob("java.*.log"):
                log.write_text("", encoding="utf-8")
            process = launch("java", java_command(), JAVA, environment)
            launched["java"] = process
            wait_java(process)
        ai = launch("ai", [
            sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
            "--app-dir", str(ROOT / "python-ai"), "--host", "127.0.0.1", "--port", str(AI_PORT),
        ], ROOT / "python-ai", environment)
        launched["ai"] = ai
        wait_http(ai, f"http://127.0.0.1:{AI_PORT}/ai/health")
        # Frontend never inherits DB credentials or service keys.
        frontend_environment = os.environ.copy()
        for name in ("DB_PASSWORD", "DB_USERNAME", "AI_SERVICE_KEY"):
            frontend_environment.pop(name, None)
        frontend_environment.update({"JAVA_PROXY_TARGET": frontend_java_target(values),
            "AI_PROXY_TARGET": f"http://127.0.0.1:{AI_PORT}", "VITE_DEMO_MODE": "true" if DEMO else "false",
            "VITE_PAYMENTS_ENABLED": payments, "VITE_COMMERCE_ENABLED": commerce})
        front = launch("frontend", [
            "node", str(ROOT / "DeepseekDoc/node_modules/vite/bin/vite.js"),
            "--host", "127.0.0.1", "--port", str(FRONT_PORT), "--strictPort",
        ], ROOT / "DeepseekDoc", frontend_environment)
        launched["frontend"] = front
        wait_http(front, f"http://127.0.0.1:{FRONT_PORT}")
        metadata = {name: {"pid": process.pid} for name, process in launched.items()}
        metadata["java"]["environmentMarker"] = "demo" if DEMO else "normal"
        metadata["legacyAccountsMigrated"] = legacy
        metadata["model"] = environment["OLLAMA_MODEL"]
        metadata["modelTemperature"] = environment["MODEL_TEMPERATURE"]
        (RUN / "stack.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(json.dumps(metadata))
    except BaseException:
        for process in reversed(list(launched.values())):
            if process.poll() is None:
                process.terminate()
        raise


def start_ai_preview():
    ensure_private()
    values = config()
    for port in (8000, 3000):
        if listening(port):
            raise RuntimeError(f"Port {port} is occupied; no existing process was stopped")
    key = values.get("AI_SERVICE_KEY")
    if not key:
        key = secrets.token_urlsafe(48)
        with CONFIG.open("a", encoding="utf-8") as file:
            file.write("\nAI_SERVICE_KEY=" + key + "\n")
        protect(CONFIG)
    environment = os.environ.copy()
    environment.update({
        "AI_SERVICE_KEY": key, "JAVA_BASE_URL": "http://127.0.0.1:8080",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": values.get("OLLAMA_MODEL", "Qwen2.5:latest"),
        "MODEL_READ_TIMEOUT_SECONDS": "60", "MODEL_TIMEOUT_SECONDS": "180",
        "MODEL_TEMPERATURE": values.get("MODEL_TEMPERATURE", "0"),
        "KNOWLEDGE_DATABASE_PATH": str(RUN / "knowledge.db"),
        "EMBEDDING_MODEL": values.get("EMBEDDING_MODEL", "bge-m3:latest"),
        "AI_DATABASE_PATH": str(RUN / "conversations.db"),
    })
    launched = {}
    try:
        ai = launch("ai", [
            sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
            "--app-dir", str(ROOT / "python-ai"), "--host", "127.0.0.1", "--port", "8000",
        ], ROOT / "python-ai", environment)
        launched["ai"] = ai
        wait_http(ai, "http://127.0.0.1:8000/ai/health")
        clean_environment = os.environ.copy()
        for name in ("DB_PASSWORD", "DB_USERNAME", "AI_SERVICE_KEY"):
            clean_environment.pop(name, None)
        frontend = launch("frontend", [
            "node", str(ROOT / "DeepseekDoc/node_modules/vite/bin/vite.js"),
            "--host", "127.0.0.1", "--port", "3000", "--strictPort",
        ], ROOT / "DeepseekDoc", clean_environment)
        launched["frontend"] = frontend
        wait_http(frontend, "http://127.0.0.1:3000")
        metadata = {name: {"pid": process.pid} for name, process in launched.items()}
        (RUN / "preview.json").write_text(json.dumps(metadata), encoding="utf-8")
        print(json.dumps({"services": metadata, "javaReady": False, "databaseChanged": False}))
    except BaseException:
        for process in reversed(list(launched.values())):
            if process.poll() is None:
                process.terminate()
        raise


def stop():
    stopped = []
    for filename in ("preview.json", "stack.json"):
        path = RUN / filename
        if not path.exists():
            continue
        metadata = json.loads(path.read_text(encoding="utf-8"))
        for name in ("frontend", "ai", "java"):
            if name not in metadata:
                continue
            pid = int(metadata[name]["pid"])
            command = (
                "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            command_line = result.stdout.strip()
            if not command_line:
                continue
            if str(ROOT).lower() not in command_line.lower():
                raise RuntimeError("Managed PID no longer belongs to this project; refusing to stop it")
            expected_port = {"frontend": FRONT_PORT, "ai": AI_PORT}.get(name)
            if expected_port and not re.search(r"--port\s+\"?" + str(expected_port) + r"(?:\s|\"|$)", command_line):
                raise RuntimeError("Managed PID belongs to another environment; refusing to stop it")
            marker = metadata[name].get("environmentMarker")
            if marker and "-Ddeepseekdoc.environment=" + marker not in command_line \
                    and str(RUN / "java.args").lower() not in command_line.lower():
                raise RuntimeError("Java environment marker mismatch; refusing to stop it")
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=True)
            stopped.append(name)
        path.unlink()
    print(json.dumps({"stopped": stopped, "ollamaKeptRunning": True}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("initialize", "prepare", "start", "start-ai-preview", "stop", "check-config"))
    args = parser.parse_args()
    if args.action == "check-config":
        values = config()
        print(json.dumps({"databaseUserConfigured": bool(values.get("DB_USERNAME")),
                          "databasePasswordConfigured": bool(values.get("DB_PASSWORD"))}))
    elif args.action == "initialize":
        initialize()
    elif args.action == "prepare":
        prepare()
    elif args.action == "start-ai-preview":
        start_ai_preview()
    elif args.action == "stop":
        stop()
    else:
        start()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, pymysql.MySQLError, subprocess.SubprocessError) as exc:
        if isinstance(exc, pymysql.MySQLError):
            print("MySQL operation failed (code " + str(exc.args[0]) + "); no credentials logged",
                  file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
