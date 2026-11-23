"""Restore the owned demo backup into a newly-created disposable schema, never over normal data."""
import json
import os
import re
import secrets

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard, normal_config
from local_stack import RUN, database, query


def main():
    guard()
    record = json.loads((RUN / "m51-migration.json").read_text(encoding="utf-8"))
    from pathlib import Path
    backup = Path(record["backup"]).resolve()
    if not backup.is_relative_to((RUN / "backups").resolve()):
        raise RuntimeError("Backup must belong to the private demo backup directory")
    text = backup.read_text(encoding="utf-8-sig")
    # mysqldump without --databases must not switch the selected target schema.
    executable = re.sub(r"/\*.*?\*/|--[^\n]*", "", text, flags=re.S)
    if re.search(r"\b(?:USE\s+|(?:CREATE|DROP)\s+DATABASE\b)", executable, re.I):
        raise RuntimeError("Backup contains a database switch; refusing restore")
    name = "DeepseekDoc_M51_Restore_" + secrets.token_hex(5)
    created = False
    with database(normal_config()) as conn:
        try:
            if query(conn, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (name,)):
                raise RuntimeError("Scratch schema already exists")
            query(conn, "CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            created = True
            conn.select_db(name)
            with conn.cursor() as cursor:
                cursor.execute(text)
                while cursor.nextset():
                    pass
            if query(conn, "SELECT DATABASE()")[0][0].casefold() != name.casefold():
                raise RuntimeError("Restore changed the database target")
            assert query(conn, "SELECT marker FROM m43_demo_environment")[0][0] == "deepseekdoc-m43-synthetic-v1"
            rows = {table: query(conn, "SELECT COUNT(*) FROM `" + table + "`")[0][0] for table in
                    ("users", "orders", "transactions", "payment_records", "payment_authorizations", "payment_operation_requests")}
            columns = {row[0] for row in query(conn, "SHOW COLUMNS FROM orders")}
            assert {"payment_status", "payment_version", "source_draft_id"} <= columns
            report = {"passed": True, "restoredIntoDisposableSchema": True, "restoredRowCounts": rows,
                      "normalDatabaseChanged": False, "paymentExecuted": False}
            (RUN / "m51-restore.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
        finally:
            if created:
                if not re.fullmatch(r"DeepseekDoc_M51_Restore_[0-9a-f]{10}", name):
                    raise RuntimeError("Scratch cleanup target mismatch")
                query(conn, "DROP DATABASE `" + name + "`")


if __name__ == "__main__":
    main()
