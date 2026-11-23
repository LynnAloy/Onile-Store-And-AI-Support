"""Compare server-side hashes, never export normal user/profile/payment values."""
import argparse
import hashlib
import json
import os
import sqlite3

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import normal_config, guard
from local_stack import ROOT, RUN, database, query


def fingerprint():
    result = {}
    values = normal_config()
    with database(values) as conn:
        for table in ("users", "medicines", "orders", "order_items", "order_drafts",
                      "order_draft_items", "profile_consent_events"):
            columns = query(conn, "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                            (values.get("DB_NAME", "DeepSeekDoc"), table))
            expressions = ["IFNULL(CAST(`" + column[0].replace("`", "``") + "` AS CHAR),'<NULL>')" for column in columns]
            hashes = query(conn, "SELECT SHA2(CONCAT_WS(CHAR(31)," + ",".join(expressions) + "),256) FROM `" + table + "`")
            result[table] = hashlib.sha256("|".join(sorted(row[0] for row in hashes)).encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("baseline", "check"))
    args = parser.parse_args()
    guard()
    snapshot = fingerprint()
    baseline = RUN / "normal-before-reset.json"
    if args.action == "baseline":
        baseline.write_text(json.dumps(snapshot), encoding="utf-8")
        with database(guard()) as conn:
            balance = query(conn, "SELECT balance=0 FROM users WHERE user_id='m43_browser'")
            stock = query(conn, "SELECT COUNT(*) FROM medicines WHERE name IN ('虚构演示甲','虚构演示乙') AND stock=50")[0][0]
            orders = query(conn, "SELECT COUNT(*) FROM orders")[0][0]
        with sqlite3.connect(RUN / "conversations.db") as conn:
            leaked = conn.execute("SELECT count(*) FROM turns WHERE message LIKE ? OR assistant LIKE ? OR tool_events LIKE ?",
                                 ("%虚构演示地址M43测试楼%",) * 3).fetchone()[0]
        evidence = {"syntheticBalanceUnchanged": balance == ((1,),), "syntheticStockUnchanged": stock == 2,
                    "completedOrdersUnchanged": orders == 0, "shippingAbsentFromAIHistory": leaked == 0}
        (ROOT / "docs/evidence/m43/financial-privacy.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        if not all(evidence.values()):
            raise RuntimeError("Demo financial/privacy invariant failed")
        print('{"normalBaselineRecorded":true,"rowValuesLogged":false}')
    else:
        before = json.loads(baseline.read_text(encoding="utf-8"))
        report = {"normalBusinessTablesUnchanged": before == snapshot,
                  "tablesChecked": list(snapshot), "normalRowValuesLogged": False}
        (ROOT / "docs/evidence/m43/isolation-reset.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        if before != snapshot:
            raise RuntimeError("Normal data changed since baseline; inspect before attributing cause")


if __name__ == "__main__":
    main()
