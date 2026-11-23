"""Static backend contract checks; actual response checks run in m51_live_smoke.py."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def validate():
    payment = json.loads((ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8"))
    agent = json.loads((ROOT / "docs/java-python-contract.openapi.json").read_text(encoding="utf-8"))
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    def references(document, value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/")
                target = document
                for part in value["$ref"][2:].split("/"):
                    target = target[part]
            for child in value.values():
                references(document, child)
        if isinstance(value, list):
            for child in value:
                references(document, child)

    for doc in (payment, agent):
        references(doc, doc)
    check("both contracts resolve local references", True)
    check("payment backend version and feature gate declared", payment["info"]["version"] in {"5.1.0", "5.1.1"}
          and payment["x-design-only"] is False and payment["x-feature-flag"] == "payments.enabled")
    operations = [op for methods in payment["paths"].values() for op in methods.values()]
    check("six implemented USER-only operations", len(operations) == 6 and all(
        op["security"] == [{"UserToken": []}] and op["x-implementation-status"] == "IMPLEMENTED_BACKEND_FEATURE_GATED" for op in operations))
    schemas = payment["components"]["schemas"]
    check("strict write DTOs exclude client financial authority", all(schemas[name]["additionalProperties"] is False
          and not {"userId", "amount", "totalPrice", "paid"} & schemas[name]["properties"].keys() for name in ("Version", "Authorize")))
    check("new and historical order schemas have disjoint states", not set(schemas["Order"]["properties"]["paymentStatus"]["enum"])
          & set(schemas["LegacyOrder"]["properties"]["paymentStatus"]["enum"]))
    check("separate authorization header and idempotency key", {p["name"] for p in payment["paths"]["/api/orders/{orderId}/pay"]["post"]["parameters"]
          if p["in"] == "header" and p["required"]} == {"X-Payment-Authorization", "Idempotency-Key"})
    summary = agent["components"]["schemas"]["OrderSummary"]
    check("AI summary preserves strict private-data whitelist", summary["additionalProperties"] is False
          and set(summary["properties"]) == {"orderId", "status", "totalPrice", "currency", "items"})
    check("AI summary covers authoritative and historical payment states", {"PENDING_PAYMENT", "PAID", "CLOSED", "LEGACY_UNVERIFIED"}
          <= set(summary["properties"]["status"]["enum"]))
    baseline = json.loads((ROOT / "docs/evidence/m43/release-manifest.json").read_text(encoding="utf-8"))
    prefixes = ("python-ai/app/",) if payment.get("x-ui-implementation-status") else ("python-ai/app/", "DeepseekDoc/src/")
    stable = {p: digest for p, digest in baseline["sourceHashes"].items() if p.startswith(prefixes)}
    check("AI runtime unchanged; implemented UI validated by frontend suite" if len(prefixes)==1 else "M4.3 AI and UI runtime source hashes unchanged", bool(stable) and all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == digest for p, digest in stable.items()))
    return {"passed": True, "checks": checks, "count": len(checks), "staticOnly": True, "validatedVersion": payment["info"]["version"], "runtimeComparisonPrefixes":prefixes}


if __name__ == "__main__":
    result = validate()
    payment = json.loads((ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8"))
    destination = ROOT / ("docs/evidence/m51d" if payment.get("x-acceptance-stage")=="M5.1-D" else "docs/evidence/m51")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "contract-static.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
