"""Bootstrap one new administrator; credentials stay in the protected local run directory."""
import argparse
import json
import os
import secrets

import httpx


def create(environment):
    os.environ["DEEPSEEKDOC_DEMO"] = "1" if environment == "demo" else "0"
    import local_stack as stack
    stack.ensure_private()
    values = stack.config()
    if stack.commerce_mode(values) != "true":
        raise RuntimeError("Deploy and verify commerce migration first")
    path = stack.RUN / "admin-account.json"
    if path.exists():
        with stack.database(values) as conn:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not stack.query(conn, "SELECT r.user_id FROM account_roles r JOIN users u ON u.id=r.user_id WHERE u.user_id=%s AND r.role='ADMIN'", (record["username"],)):
                raise RuntimeError("Existing administrator record does not match the protected credential file")
        print(json.dumps({"adminAlreadyCreated": True, "credentialFile": str(path)}))
        return
    username = "admin_m6_" + secrets.token_hex(4)
    password = secrets.token_urlsafe(24)
    # Persist before registration so an interrupted bootstrap never loses the generated credential.
    path.write_text(json.dumps({"username": username, "password": password, "environment": environment}, indent=2), encoding="utf-8")
    stack.protect(path)
    with httpx.Client(base_url=f"http://127.0.0.1:{stack.JAVA_PORT}", trust_env=False, timeout=15) as client:
        response = client.post("/api/auth/register", json={"userId": username, "password": password})
        if response.status_code != 200:
            raise RuntimeError("Administrator registration failed; inspect protected bootstrap record")
    with stack.database(values) as conn:
        row = stack.query(conn, "SELECT id FROM users WHERE user_id=%s", (username,))
        if len(row) != 1:
            raise RuntimeError("New account could not be verified")
        stack.query(conn, "INSERT INTO account_roles(user_id,role,granted_at) VALUES (%s,'ADMIN',UNIX_TIMESTAMP())", (row[0][0],))
        stack.query(conn, "DELETE FROM auth_sessions WHERE user_id=%s", (row[0][0],))
    print(json.dumps({"adminCreated": True, "credentialFile": str(path), "existingUsersPromoted": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("normal", "demo"), required=True)
    create(parser.parse_args().environment)
