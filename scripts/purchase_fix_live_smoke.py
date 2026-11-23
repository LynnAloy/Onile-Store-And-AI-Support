"""Reproduce the user's exact quantity request against the unchanged public catalog."""
import json
import sys
import time
import uuid

from live_smoke import Smoke, check
from local_stack import RUN, ensure_private, query


class PurchaseSmoke(Smoke):
    def run(self):
        name = self.names[0]
        self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
        token = self.request("POST", "/api/auth/login", data={"userId": name, "password": self.password})["token"]
        agent = self.request("POST", "/api/auth/agent-token", token)["token"]
        before = query(self.conn, "SELECT id,name,stock,sale_classification,review_status FROM medicines "
                       "WHERE name IN (%s,%s) ORDER BY id", ("枇杷露", "布洛芬"))
        check(len(before) == 2, "Required public catalog products are missing")
        cid = self.request("POST", "/ai/v1/conversations", agent, {"title": "合成数量回归"}, expected=201)["id"]
        rid = str(uuid.uuid4())
        prompt = "帮我下单5件枇杷露，3件布洛芬"
        parsed = []
        with self.http.stream("POST", self.base + f"/ai/v1/conversations/{cid}/messages",
                headers={"Authorization": "Bearer " + agent}, json={"message": prompt, "requestId": rid}) as response:
            check(response.status_code == 200, "Quantity stream failed")
            kind = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    item = json.loads(line[5:].strip())
                    parsed.append((kind, item))
                    if kind == "error":
                        raise RuntimeError("Native quantity pipeline failed: " + item.get("code", "UNKNOWN"))
        check(parsed[-1][0] == "done", "Quantity stream did not complete")
        proposals = [data["result"]["proposal"] for kind, data in parsed
                     if kind == "tool_result" and data["tool"] == "propose_purchase" and data["result"]["ok"]]
        check(bool(proposals), "Model did not invoke native propose_purchase")
        proposal = proposals[-1]
        quantities = {item["name"]: item["quantity"] for item in proposal["items"]}
        check(quantities == {"枇杷露": 5, "布洛芬": 3}, "Explicit quantities lost or exchanged")
        check(all(item["autoSelect"] for item in proposal["items"]), "Unique named products should be selectable")
        self.record("Exact prompt produces native catalog lookups and validated 5/3 purchase checklist",
                    quantities=quantities)

        check(all(item["draftEligible"] is False for item in proposal["items"]), "Unknown qualification was bypassed")
        check(proposal["requiresUserAuthorization"] is True, "Preview became an authorization")
        owned = query(self.conn, "SELECT count(*) FROM order_drafts d JOIN users u ON u.id=d.user_id "
                      "WHERE u.user_id=%s", (name,))[0][0]
        check(owned == 0, "Read-only preview created a draft")
        self.record("Unreviewed products remain blocked while requested quantities are preserved; no draft created")

        history = self.request("GET", f"/ai/v1/conversations/{cid}/messages", agent)
        stored = [event["data"]["result"]["proposal"] for event in history["turns"][0]["toolEvents"]
                  if event["kind"] == "tool_result" and event["data"]["tool"] == "propose_purchase"]
        check(stored[-1] == proposal, "History lost structured quantities")
        replay = self.stream(cid, agent, prompt, rid)
        check(replay["replayed"] and "枇杷露 ×5" in replay["answer"] and "布洛芬 ×3" in replay["answer"],
              "Replay or quantity prose changed")
        self.record("History and cached response retain exact item quantities without reauthorization")

        items = [{"medicineId": item["id"], "quantity": item["quantity"]} for item in proposal["items"]]
        grant = self.request("POST", "/api/auth/order-agent-token", token, {"items": items})
        result = self.http.post(self.java_base + "/internal/ai/v1/order-drafts",
            headers={"Authorization": "Bearer " + grant["token"], "X-AI-Service-Key": self.values["AI_SERVICE_KEY"],
                     "Idempotency-Key": grant["requestKey"]}, json={"items": items})
        check(result.status_code == 409 and result.json()["code"] == "SALE_NOT_ALLOWED",
              "Preview selection incorrectly approved a product")
        after = query(self.conn, "SELECT id,name,stock,sale_classification,review_status FROM medicines "
                      "WHERE name IN (%s,%s) ORDER BY id", ("枇杷露", "布洛芬"))
        check(before == after, "Catalog qualification or inventory changed")
        self.record("Java eligibility gate still rejects draft preparation; real catalog is unchanged")


def main():
    ensure_private()
    smoke = PurchaseSmoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception:
            failure = (failure or "") + " Scoped fixture cleanup failed"
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "realServices": True,
              "checks": smoke.results, "passed": failure is None, "failure": failure,
              "normalUserDataChanged": False, "credentialsLogged": False}
    (RUN / "purchase-fix-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())

