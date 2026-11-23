"""Recover only successful registrations recorded by this isolated smoke-test environment."""
import json
import os

os.environ["DEEPSEEKDOC_DEMO"] = "1"
import httpx
from demo import guard
from live_smoke import Smoke, check
from local_stack import RUN, database, query, target_fingerprint


def main():
    values = guard()
    cleaned = 0
    for path in (RUN / "fixtures").glob("it_*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        check(manifest["targetFingerprint"] == target_fingerprint(values), "Fixture database mismatch")
        smoke = object.__new__(Smoke)
        smoke.conn = database(values)
        try:
            for user in manifest["users"]:
                found = query(smoke.conn, "SELECT id FROM users WHERE user_id=%s", (user["name"],))
                check(not found or found == ((user["id"],),), "Fixture identity was replaced; refusing deletion")
        except BaseException:
            smoke.conn.close()
            raise
        smoke.created_names = [user["name"] for user in manifest["users"]]
        smoke.product = manifest["product"]
        smoke.product_name = manifest["productName"]
        smoke.card, smoke.card_b = manifest["card"], manifest["cardB"]
        smoke.fixture_path = path
        smoke.http = httpx.Client(trust_env=False)
        smoke.cleanup()
        cleaned += 1
    print(json.dumps({"recoveredFixtureRuns": cleaned, "normalDatabaseChanged": False}))


if __name__ == "__main__":
    main()
