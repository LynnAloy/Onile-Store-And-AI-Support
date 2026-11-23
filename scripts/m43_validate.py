"""One command for isolated real-service regression; browser proof is a separate CUA run."""
import argparse
import json
import os
import subprocess
import sys
import time

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard
from local_stack import ROOT, RUN


def verify_business_cases():
    definition = json.loads((ROOT / "scripts/m43-business-cases.json").read_text(encoding="utf-8"))
    report = json.loads((RUN / definition["resultFile"]).read_text(encoding="utf-8"))
    passed = {row["check"] for row in report["checks"] if row["passed"]}
    return report["passed"] and all(case["expectedCheck"] in passed for case in definition["cases"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-evaluation", action="store_true")
    args = parser.parse_args()
    guard()
    scripts = ["live_smoke.py", "m3_live_smoke.py", "m4_live_smoke.py", "m42_live_smoke.py"]
    if not args.skip_evaluation:
        scripts.append("m43_evaluate.py")
    rows = []
    for script in scripts:
        started = time.monotonic()
        log = RUN / "logs" / ("m43-" + script + ".log")
        with log.open("w", encoding="utf-8") as output:
            result = subprocess.run([sys.executable, "-u", "-X", "utf8", str(ROOT / "scripts" / script)],
                                    stdout=output, stderr=subprocess.STDOUT, timeout=1200)
        rows.append({"script": script, "passed": result.returncode == 0,
                     "seconds": round(time.monotonic() - started, 2), "log": log.name})
        if script == "m42_live_smoke.py":
            rows[-1]["fixedBusinessCasesPassed"] = verify_business_cases()
            rows[-1]["passed"] = rows[-1]["passed"] and rows[-1]["fixedBusinessCasesPassed"]
        print(json.dumps(rows[-1]))
        (RUN / "m43-regression.json").write_text(json.dumps({"checks": rows, "running": True,
            "passed": False}, indent=2), encoding="utf-8")
    (RUN / "m43-regression.json").write_text(json.dumps({"checks": rows, "running": False,
        "passed": all(row["passed"] for row in rows)}, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
