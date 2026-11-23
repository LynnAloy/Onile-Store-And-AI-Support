"""Explicit local deployment of admin and consented autonomous demo-wallet commerce."""
import argparse
import hashlib
import json
import os
import re


def payment_statements(root):
    source = re.sub(r"--[^\n]*", "", (root / "docs/sql/M5.1-A.proposed.sql").read_text(encoding="utf-8"))
    for statement in source.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        match = re.match(r"ALTER TABLE (\w+)\s+(.*)", statement, re.S)
        if not match:
            yield None, statement
            continue
        table, body = match.groups()
        depth, start = 0, 0
        for index, char in enumerate(body):
            depth += (char == "(") - (char == ")")
            if char == "," and depth == 0:
                yield table, body[start:index].strip()
                start = index + 1
        yield table, body[start:].strip()


def migrate(environment):
    os.environ["DEEPSEEKDOC_DEMO"] = "1" if environment == "demo" else "0"
    import local_stack as stack
    values = stack.config()
    if values.get("DB_HOST", "127.0.0.1") not in ("127.0.0.1", "localhost"):
        raise RuntimeError("This deployment only accepts the configured local MySQL")
    stack.ensure_private()
    prepared = json.loads((stack.RUN / "prepared.json").read_text(encoding="utf-8"))
    if prepared.get("targetFingerprint") != stack.target_fingerprint(values):
        raise RuntimeError("Target differs from the backed-up project database")
    if stack.listening(stack.JAVA_PORT):
        raise RuntimeError("Stop this environment's managed Java service before migration")
    proof = stack.RUN / "m6-migration.json"
    if proof.exists():
        stack.commerce_mode(values)  # Refuse drift before certifying an existing installation.
    destination = stack.backup(values)
    applied = 0
    with stack.database(values) as conn:
        required = {"users", "medicines", "orders", "order_items", "order_drafts", "transactions"}
        if not required <= {row[0] for row in stack.query(conn, "SHOW TABLES")}:
            raise RuntimeError("Unexpected project schema")
        stack.query(conn, "CREATE TABLE IF NOT EXISTS m51_migration_steps(step_hash CHAR(64) PRIMARY KEY, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        for table, clause in payment_statements(stack.ROOT):
            sql = "ALTER TABLE " + table + " " + clause if table else clause
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if stack.query(conn, "SELECT step_hash FROM m51_migration_steps WHERE step_hash=%s", (digest,)):
                continue
            if table:
                column = re.match(r"ADD COLUMN (\w+)", clause)
                constraint = re.match(r"ADD (?:CONSTRAINT|UNIQUE KEY) (\w+)", clause)
                if column:
                    rows = stack.query(conn, "SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s", (table, column[1]))
                    if rows:
                        expected = re.match(r"ADD COLUMN \w+\s+(\w+(?:\([^)]*\))?)\s+NULL", clause)
                        if not expected or rows[0] != (expected[1].lower(), "YES"):
                            raise RuntimeError("Unexpected existing payment column")
                    exists = bool(rows)
                elif constraint:
                    exists = bool(stack.query(conn, "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (table, constraint[1])))
                else:
                    raise RuntimeError("Unsupported payment migration statement")
            else:
                name = re.match(r"CREATE TABLE (\w+)", clause)[1]
                exists = bool(stack.query(conn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (name,)))
            if not exists:
                stack.query(conn, sql)
                applied += 1
            stack.query(conn, "INSERT INTO m51_migration_steps(step_hash) VALUES (%s)", (digest,))
        source = (stack.ROOT / "docs/sql/M6-commerce.sql").read_text(encoding="utf-8")
        for statement in re.sub(r"--[^\n]*", "", source).split(";"):
            if statement.strip():
                stack.query(conn, statement)
    report = {"passed": True, "environment": environment, "backup": str(destination),
              "targetFingerprint": stack.target_fingerprint(values),
              "schemaSha256": hashlib.sha256((stack.ROOT / "docs/sql/M6-commerce.sql").read_bytes()).hexdigest(),
              "paymentSchemaSha256": hashlib.sha256((stack.ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest(),
              "paymentStructureSha256": stack.payment_schema_fingerprint(values),
              "commerceStructureSha256": stack.commerce_schema_fingerprint(values),
              "paymentStatementsApplied": applied, "existingQualificationsChanged": False,
              "existingWalletConsentsChanged": False}
    proof.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "environment", "paymentStatementsApplied", "existingQualificationsChanged", "existingWalletConsentsChanged")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("normal", "demo"), required=True)
    migrate(parser.parse_args().environment)
