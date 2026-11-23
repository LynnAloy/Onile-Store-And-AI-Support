"""Offline checks for the frozen design; not a runtime payment or full OpenAPI conformance test."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def validate():
    archive = ROOT / "docs/archive/m51-payment-design.openapi.json"
    document = json.loads((archive if archive.exists() else ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "docs/M5.1-A-acceptance.json").read_text(encoding="utf-8"))
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    check("design is explicitly not implemented", document["x-design-only"] is True)
    operations = [op for path in document["paths"].values() for op in path.values()]
    check("six USER-only operations", len(operations) == 6 and all(
        op["security"] == [{"UserToken": []}] and op["x-implementation-status"] == "NOT_IMPLEMENTED" for op in operations))

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = document
                for part in value["$ref"].removeprefix("#/").split("/"):
                    target = target[part]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
    check("all local references resolve", True)
    schemas = document["components"]["schemas"]
    check("write DTOs reject client identity and amount", all(
        schemas[name]["additionalProperties"] is False and not {"userId", "amount", "totalPrice", "paid"}
        & set(schemas[name]["properties"]) for name in ("Version", "Authorize")))
    check("PIN is a write-only string", schemas["Authorize"]["properties"]["password"]["type"] == "string"
          and schemas["Authorize"]["properties"]["password"]["writeOnly"])
    line = schemas["Line"]["properties"]
    check("integer quantities and fixed decimal money", line["quantity"] == {"type": "integer", "minimum": 1, "maximum": 99}
          and line["price"]["type"] == "string" and re.fullmatch(line["price"]["pattern"], "10.00")
          and not re.fullmatch(line["price"]["pattern"], "10.001"))
    pay = document["paths"]["/api/orders/{orderId}/pay"]["post"]
    headers = {p["name"] for p in pay["parameters"] if p["in"] == "header" and p["required"]}
    check("payment capability is separate from USER identity", headers == {"Idempotency-Key", "X-Payment-Authorization"})
    revoke = document["paths"]["/api/orders/{orderId}/payment-authorizations"]["delete"]
    check("late authorizations support scoped revocation", any(p["name"] == "authorizationId" and not p["required"] for p in revoke["parameters"]))
    check("private success responses prohibit caching", all(op["responses"]["200"]["headers"]["Cache-Control"]["schema"]["enum"] == ["no-store"] for op in operations))
    check("versioned acceptance vectors are specifications", cases["executionStatus"] == "SPECIFICATION_ONLY"
          and len(cases["cases"]) == 15 and len({case["id"] for case in cases["cases"]}) == 15)
    sql_path = ROOT / "docs/sql/M5.1-A.proposed.sql"
    sql = sql_path.read_text(encoding="utf-8")
    statements = [part.strip() for part in re.sub(r"--[^\n]*", "", sql).split(";") if part.strip()]
    check("migration proposal is additive DDL only", len(statements) == 5 and all(
        part.startswith(("ALTER TABLE ", "CREATE TABLE ")) for part in statements))
    stack = (ROOT / "scripts/local_stack.py").read_text(encoding="utf-8")
    check("no automatic payment DDL execution", "m51_migrate" not in stack and sql_path.parent == ROOT / "docs/sql")
    check("source/order and payment/ledger uniqueness", all(term in sql for term in (
        "uq_orders_source_draft", "order_id VARCHAR(30) NOT NULL UNIQUE", "ledger_id VARCHAR(30) NOT NULL UNIQUE",
        "PRIMARY KEY(user_id,operation,request_key)")))
    baseline = json.loads((ROOT / "docs/evidence/m43/release-manifest.json").read_text(encoding="utf-8"))
    current = json.loads((ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8"))
    ui_implemented = bool(current.get("x-ui-implementation-status"))
    prefixes = ("python-ai/app/",) if ui_implemented else ("python-ai/app/", "DeepseekDoc/src/") if archive.exists() else ("python-ai/app/", "DeepseekDoc/src/", "mybatis-plus-demo/")
    active = {name: digest for name, digest in baseline["sourceHashes"].items() if name.startswith(prefixes)}
    check("AI runtime source hashes unchanged; implemented UI is checked separately" if ui_implemented else "M4.3 AI/UI sources unchanged" if archive.exists() else "M4.3 runtime sources unchanged", all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in active.items()))
    return {"passed": True, "checks": checks, "count": len(checks), "acceptanceVectors": 15,
            "mysqlDDLExecutedByThisCheck": False, "paymentExecutedByThisCheck": False,
            "runtimeComparisonPrefixes": prefixes,
            "limitations": "Frozen design static recheck only. Implemented Java/UI changes require the current runtime suites; this result does not freeze or validate those sources."}


if __name__ == "__main__":
    result = validate()
    destination = "docs/M5.1-A-archive-validation.json" if (ROOT / "docs/archive/m51-payment-design.openapi.json").exists() else "docs/M5.1-A-validation.json"
    if json.loads((ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8")).get("x-acceptance-stage") == "M5.1-D":
        destination = "docs/evidence/m51d/design-archive-static.json"
    (ROOT / destination).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
