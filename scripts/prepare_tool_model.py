"""Create an independent project alias using existing weights and the official Qwen template."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import httpx

from local_stack import CONFIG, ROOT, RUN, ensure_private, protect


MODEL = "deepseekdoc-qwen2.5-tools:latest"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="Qwen2.5:latest")
    parser.add_argument("--use-local-config", action="store_true")
    args = parser.parse_args()
    ensure_private()
    template = (ROOT / "scripts/ollama/qwen2.5-tools.gotmpl").read_text(encoding="utf-8")
    with httpx.Client(trust_env=False, timeout=90) as client:
        base = "http://127.0.0.1:11434"
        source = client.post(base + "/api/show", json={"model": args.source})
        source.raise_for_status()
        if source.json().get("model_info", {}).get("general.architecture") != "qwen2":
            raise RuntimeError("Source must be an installed compatible Qwen2.5 model")
        existing = client.post(base + "/api/show", json={"model": MODEL})
        if existing.status_code == 200:
            if existing.json().get("template", "").strip() != template.strip():
                raise RuntimeError("Project alias exists with a different template; refusing to overwrite")
        elif existing.status_code == 404:
            created = client.post(base + "/api/create", json={
                "model": MODEL, "from": args.source, "template": template, "stream": False,
            })
            created.raise_for_status()
            if created.json().get("status") != "success":
                raise RuntimeError("Project model alias creation failed")
        else:
            existing.raise_for_status()
        tags = client.get(base + "/api/tags")
        tags.raise_for_status()
        digests = {item["name"]: item["digest"] for item in tags.json()["models"]}
    if args.use_local_config:
        text = CONFIG.read_text(encoding="utf-8-sig")
        if re.search(r"(?m)^OLLAMA_MODEL=.*$", text):
            text = re.sub(r"(?m)^OLLAMA_MODEL=.*$", "OLLAMA_MODEL=" + MODEL, text)
        else:
            text += "\nOLLAMA_MODEL=" + MODEL + "\n"
        CONFIG.write_text(text, encoding="utf-8")
        protect(CONFIG)
    result = {"model": MODEL, "source": args.source, "sourceDigest": digests.get(args.source),
              "modelDigest": digests.get(MODEL), "templateSha256": hashlib.sha256(template.encode()).hexdigest(),
              "localConfigUpdated": args.use_local_config, "originalModelPreserved": True}
    (RUN / "tool-model.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

