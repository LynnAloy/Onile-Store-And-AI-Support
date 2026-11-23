"""Versioned real-model evaluation; reports failures rather than selecting successful runs."""
import hashlib
import json
import os
import time
import uuid

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from live_smoke import Smoke, check
from local_stack import ROOT, RUN, query


def frames(smoke, cid, token, prompt):
    events = []
    with smoke.http.stream("POST", smoke.base + f"/ai/v1/conversations/{cid}/messages",
            headers={"Authorization": "Bearer " + token},
            json={"requestId": str(uuid.uuid4()), "message": prompt}) as response:
        response.raise_for_status()
        kind = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                events.append((kind, json.loads(line[5:].strip())))
    return events


def main():
    guard()
    dataset = json.loads((ROOT / "scripts/m43-cases.json").read_text(encoding="utf-8"))
    smoke = Smoke()
    rows = []
    try:
        smoke.request("POST", "/api/auth/register", data={"userId": smoke.names[0], "password": smoke.password})
        user = smoke.request("POST", "/api/auth/login", data={"userId": smoke.names[0], "password": smoke.password})["token"]
        agent = smoke.request("POST", "/api/auth/agent-token", user)["token"]
        for repeat in range(dataset["repeats"]):
            for case in dataset["cases"]:
                started = time.monotonic()
                row = {"id": case["id"], "repeat": repeat + 1, "passed": False}
                try:
                    cid = smoke.request("POST", "/ai/v1/conversations", agent, {"title": "合成固定评测"}, expected=201)["id"]
                    events = frames(smoke, cid, agent, case["prompt"])
                    tools = [value for kind, value in events if kind == "tool_result"]
                    row["toolResults"] = tools
                    row["nativeProposalCall"] = any(value["tool"] == "propose_purchase"
                        and value.get("invocationSource", "model") == "model" for value in tools)
                    row["runtimeProposalFallback"] = any(value.get("invocationSource") == "runtime_grounded" for value in tools)
                    row["answer"] = "".join(value["text"] for kind, value in events if kind == "delta")
                    row["errors"] = [value for kind, value in events if kind == "error"]
                    proposals = [value["result"]["proposal"] for value in tools
                                 if value["tool"] == "propose_purchase" and value["result"].get("ok")]
                    row["nativeCatalogCall"] = any(value["tool"] in ("search_medicines", "get_medicine") for value in tools)
                    row["completed"] = bool(events) and events[-1][0] == "done"
                    items = proposals[-1]["items"] if proposals else []
                    row["observedItems"] = [{key: item.get(key) for key in
                        ("name", "quantity", "autoSelect", "draftEligible", "stock")} for item in items]
                    expected = case.get("quantities")
                    if expected is not None:
                        row["productMatch"] = set(expected) == {item["name"] for item in items}
                        row["quantityAccurate"] = expected == {item["name"]: item["quantity"] for item in items}
                    else:
                        # Safe clarification without a proposal is also correct for unspecified variants.
                        row["ambiguitySafe"] = (bool(items) and all(not item["autoSelect"] for item in items)) or (
                            not items and "规格" in row["answer"] and "选择" in row["answer"])
                    if case.get("blocked"):
                        row["blockedCorrectly"] = bool(items) and all(not item["draftEligible"] for item in items)
                    if case.get("zeroStock"):
                        row["blockedCorrectly"] = bool(items) and all(item["stock"] == 0 for item in items)
                    row["draftBusinessSuccess"] = None  # Read-only proposals are never counted as draft success.
                    row["passed"] = all(row[key] for key in ("nativeCatalogCall", "completed")) and all(
                        row.get(key, True) for key in ("productMatch", "quantityAccurate", "ambiguitySafe", "blockedCorrectly"))
                except Exception as exc:
                    row["errorType"] = type(exc).__name__
                row["seconds"] = round(time.monotonic() - started, 3)
                rows.append(row)
                # Incremental persistence survives model/runtime interruption, without credentials or prompts with PHI.
                (RUN / "evaluation-rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({key: row[key] for key in ("id", "repeat", "passed", "seconds")}))
        check(query(smoke.conn, "SELECT count(*) FROM order_drafts d JOIN users u ON d.user_id=u.id WHERE u.user_id=%s",
                    (smoke.names[0],))[0][0] == 0, "Read-only evaluation created drafts")
    finally:
        smoke.cleanup()
    import httpx
    with httpx.Client(trust_env=False) as client:
        tags = client.get("http://127.0.0.1:11434/api/tags").json()["models"]
    report = {"datasetVersion": dataset["version"], "repeats": dataset["repeats"], "rows": rows,
        "model": [{key: item.get(key) for key in ("name", "digest")} for item in tags
                  if item["name"] == smoke.values["OLLAMA_MODEL"]],
        "toolTemplateSha256": hashlib.sha256((ROOT / "scripts/ollama/qwen2.5-tools.gotmpl").read_bytes()).hexdigest(),
        "knowledgeManifestSha256": hashlib.sha256((ROOT / "python-ai/knowledge/manifest.json").read_bytes()).hexdigest(),
        "agentSha256": hashlib.sha256((ROOT / "python-ai/app/agent.py").read_bytes()).hexdigest(),
        "modelClientSha256": hashlib.sha256((ROOT / "python-ai/app/model.py").read_bytes()).hexdigest(),
        "passed": all(row["passed"] for row in rows), "sampleSize": len(rows),
        "metrics": {key: {"correct": sum(bool(row[key]) for row in rows if key in row),
                          "total": sum(key in row for row in rows)} for key in
                    ("productMatch", "quantityAccurate", "nativeCatalogCall", "ambiguitySafe", "blockedCorrectly")},
        "limitations": "Small synthetic local-model sample; not clinical evaluation or production reliability."}
    (RUN / "m43-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
