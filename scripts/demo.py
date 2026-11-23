"""Isolated synthetic M4.3 environment. Never reset the normal project database."""
import argparse
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

os.environ["DEEPSEEKDOC_DEMO"] = "1"
import local_stack as stack

NAME = "DeepseekDoc_M43_Demo"
MARKER = "deepseekdoc-m43-synthetic-v1"


def normal_config():
    values = {}
    for line in (stack.ROOT / ".env.local").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if values.get("DB_NAME", "DeepSeekDoc").lower() == NAME.lower():
        raise RuntimeError("Demo database must differ from the normal database")
    return values


def guard():
    normal_config()
    values = stack.config()
    if values.get("DB_NAME") != NAME:
        raise RuntimeError("Refusing a non-demo target")
    with stack.database(values) as conn:
        rows = stack.query(conn, "SELECT marker FROM m43_demo_environment")
        if rows != ((MARKER,),):
            raise RuntimeError("Demo ownership marker mismatch; refusing mutation")
    return values


def initialize():
    source = normal_config()
    if stack.CONFIG.exists():
        guard()
        isolate_credentials()
        extend_fixtures()
        print('{"demoAlreadyInitialized":true}')
        return
    values = {**source, "DB_NAME": NAME, "AI_SERVICE_KEY": secrets.token_urlsafe(48)}
    # Preserve a partial initialization for diagnosis; never silently take over an existing schema.
    stack.RUN.mkdir(exist_ok=True)
    stack.protect(stack.RUN, directory=True)
    stack.CONFIG.write_text("\n".join(key + "=" + value for key, value in values.items()) + "\n", encoding="utf-8")
    stack.protect(stack.CONFIG)
    try:
        stack.initialize()
    except BaseException:
        stack.CONFIG.unlink()
        raise
    with stack.database(values) as conn:
        stack.query(conn, "CREATE TABLE m43_demo_environment(marker varchar(80) PRIMARY KEY)")
        stack.query(conn, "INSERT INTO m43_demo_environment VALUES (%s)", (MARKER,))
    stack.prepare()
    seed()
    extend_fixtures()
    isolate_credentials()


def extend_fixtures():
    values = guard()
    with stack.database(values) as conn:
        for name in ("虚构边界甲", "虚构边界乙", "虚构边界丙"):
            if not stack.query(conn, "SELECT id FROM medicines WHERE name=%s", (name,)):
                stack.query(conn, "INSERT INTO medicines(name,price,stock,sale_classification,review_status,"
                    "reference_source,reviewed_by,qualification_version) VALUES (%s,1.25,50,'OTC','APPROVED',%s,%s,1)",
                    (name, "local://synthetic-tests/m43", "synthetic-demo"))


def isolate_credentials():
    values = guard()
    if values["DB_USERNAME"].startswith("ddm43_"):
        return
    username = "ddm43_" + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    with stack.database(normal_config()) as admin:
        stack.query(admin, "CREATE USER %s@'localhost' IDENTIFIED BY %s", (username, password))
        stack.query(admin, "GRANT ALL PRIVILEGES ON `DeepseekDoc_M43_Demo`.* TO %s@'localhost'", (username,))
    isolated = {**values, "DB_USERNAME": username, "DB_PASSWORD": password}
    # Verify the restricted login before replacing the demo configuration.
    with stack.database(isolated) as conn:
        stack.query(conn, "SELECT marker FROM m43_demo_environment")
    stack.CONFIG.write_text("\n".join(key + "=" + value for key, value in isolated.items()) + "\n", encoding="utf-8")
    stack.protect(stack.CONFIG)
    stack.prepare()


def seed():
    values = guard()
    with stack.database(values) as conn:
        # The entire dedicated schema belongs to this demonstration; normal schema is never selected.
        if stack.query(conn, "SELECT count(*) FROM medicines")[0][0] != 3:
            raise RuntimeError("Seed expects only the three untouched bootstrap products")
        stack.query(conn, "DELETE FROM medicines")
        fixtures = [("虚构演示甲", "OTC", "APPROVED", 50), ("虚构演示乙", "OTC", "APPROVED", 50),
                    ("虚构待审核", "UNKNOWN", "PENDING", 50), ("虚构处方", "RX", "APPROVED", 50),
                    ("虚构缺货", "OTC", "APPROVED", 0), ("虚构多规格小", "OTC", "APPROVED", 50),
                    ("虚构多规格大", "OTC", "APPROVED", 50)]
        for name, category, review, stock in fixtures:
            stack.query(conn, "INSERT INTO medicines(name,price,stock,sale_classification,review_status,"
                "reference_source,reviewed_by,qualification_version) VALUES (%s,1.25,%s,%s,%s,%s,%s,1)",
                (name, stock, category, review, "local://synthetic-tests/m43", "synthetic-demo"))
    password = secrets.token_urlsafe(18)
    # Registration after startup uses the same BCrypt path as real users.
    (stack.RUN / "browser-account.json").write_text(json.dumps({"userId": "m43_browser", "password": password}), encoding="utf-8")
    stack.protect(stack.RUN / "browser-account.json")
    print('{"seededSyntheticProducts":7}')


def register():
    guard()
    import httpx
    account = json.loads((stack.RUN / "browser-account.json").read_text(encoding="utf-8"))
    with httpx.Client(trust_env=False) as client:
        response = client.post("http://127.0.0.1:13000/api/auth/register", json=account)
        if response.status_code not in (200, 409):
            raise RuntimeError("Demo registration failed")
    print('{"browserAccountReady":true,"credentialFile":".local-demo/browser-account.json"}')


def reset():
    values = guard()
    stack.stop()
    # Explicit owned schema, checked marker, separate normal target; no computed recursive file deletion.
    with stack.database(values) as conn:
        stack.query(conn, "DROP DATABASE `DeepseekDoc_M43_Demo`")
    if values["DB_USERNAME"].startswith("ddm43_"):
        with stack.database(normal_config()) as admin:
            stack.query(admin, "DROP USER %s@'localhost'", (values["DB_USERNAME"],))
    for path in (stack.RUN / "fixtures").glob("it_*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("targetFingerprint") == stack.target_fingerprint(values):
            path.unlink()
    stack.CONFIG.unlink()
    for name in ("conversations.db", "knowledge.db", "conversations.db-wal", "conversations.db-shm",
                 "knowledge.db-wal", "knowledge.db-shm", "prepared.json", "browser-account.json",
                 "browser-alt-account.json", "browser-boundary-fixtures.json"):
        (stack.RUN / name).unlink(missing_ok=True)
    (stack.RUN / "m51-migration.json").unlink(missing_ok=True)
    print('{"isolatedDemoRemoved":true,"normalDatabasePreserved":true}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("initialize", "start", "stop", "reset", "register", "knowledge"))
    args = parser.parse_args()
    if args.action == "initialize":
        initialize()
    elif args.action == "reset":
        reset()
    else:
        guard()
        if args.action == "start":
            stack.start()
            register()
        elif args.action == "stop":
            stack.stop()
        elif args.action == "register":
            register()
        else:
            subprocess.run([sys.executable, str(stack.ROOT / "scripts/run_knowledge.py"), "sync",
                str(stack.ROOT / "python-ai/knowledge/manifest.json")], check=True)


if __name__ == "__main__":
    main()
