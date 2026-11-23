"""Explicit isolated-demo M5 migration. Normal project schema is never selected."""
import argparse
import hashlib
import json
import os
import re

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from local_stack import ROOT, RUN, backup, database, query, listening, target_fingerprint, payment_schema_fingerprint


def statements():
    sql = re.sub(r"--[^\n]*", "", (ROOT / "docs/sql/M5.1-A.proposed.sql").read_text(encoding="utf-8"))
    result = []
    for statement in sql.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        if statement.startswith("ALTER TABLE"):
            match = re.match(r"ALTER TABLE (\w+)\s+(.*)", statement, re.S)
            table, body = match.groups()
            depth, start = 0, 0
            for index, char in enumerate(body):
                depth += (char == "(") - (char == ")")
                if char == "," and depth == 0:
                    result.append((table, body[start:index].strip()))
                    start = index + 1
            result.append((table, body[start:].strip()))
        else:
            result.append((None, statement))
    return result


def migrate(fail_after=None):
    values = guard()
    if listening(18080):
        raise RuntimeError("Stop only the demo stack before migrating")
    if (RUN / "m51-migration.json").exists():
        prior = json.loads((RUN / "m51-migration.json").read_text(encoding="utf-8"))
        if prior.get("databaseStructureSha256") and prior["databaseStructureSha256"] != payment_schema_fingerprint(values):
            raise RuntimeError("Existing completed payment schema drifted; refusing to certify it")
    destination = backup(values)
    applied = 0
    with database(values) as conn:
        query(conn, "CREATE TABLE IF NOT EXISTS m51_migration_steps(step_hash CHAR(64) PRIMARY KEY, completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        for table, clause in statements():
            sql = "ALTER TABLE " + table + " " + clause if table else clause
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if query(conn, "SELECT step_hash FROM m51_migration_steps WHERE step_hash=%s", (digest,)):
                continue
            # Check actual metadata too: process may die after DDL implicit commit but before recording it.
            exists = False
            if table:
                column = re.match(r"ADD COLUMN (\w+)", clause)
                constraint = re.match(r"ADD (?:CONSTRAINT|UNIQUE KEY) (\w+)", clause)
                if column:
                    exists = bool(query(conn, "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s", (table, column[1])))
                    if exists:
                        expected = re.match(r"ADD COLUMN \w+\s+(\w+(?:\([^)]*\))?)\s+NULL", clause)
                        actual = query(conn, "SELECT COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s", (table,column[1]))[0]
                        if not expected or actual[0].lower() != expected[1].lower() or actual[1] != "YES":
                            raise RuntimeError("Existing migration column differs from the proposed definition")
                elif constraint:
                    exists = bool(query(conn, "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s", (table, constraint[1])))
            else:
                name = re.match(r"CREATE TABLE (\w+)", clause)[1]
                exists = bool(query(conn, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (name,)))
            if not exists:
                query(conn, sql)
                applied += 1
                if fail_after is not None and applied == fail_after:
                    raise RuntimeError("Synthetic interruption after committed DDL; rerun to resume")
            query(conn, "INSERT INTO m51_migration_steps(step_hash) VALUES (%s)", (digest,))
        # A structural check before permitting the demo-only feature flag.
        query(conn, "SELECT source_draft_id,payment_status,payment_version FROM orders LIMIT 0")
        for name in ("payment_records", "payment_authorizations", "payment_operation_requests"):
            query(conn, "SELECT * FROM " + name + " LIMIT 0")
    report = {"passed": True, "appliedStatements": applied, "backup": str(destination),
              "target": "DeepseekDoc_M43_Demo", "normalDatabaseChanged": False,
              "targetFingerprint": target_fingerprint(values),
              "databaseStructureSha256": payment_schema_fingerprint(values),
              "schemaSha256": hashlib.sha256((ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest()}
    (RUN / "m51-migration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-after", type=int)
    migrate(parser.parse_args().fail_after)
