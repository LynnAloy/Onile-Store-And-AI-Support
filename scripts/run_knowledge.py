"""Run local knowledge administration without exposing credentials on command lines."""
import os
import subprocess
import sys

from local_stack import ROOT, RUN, config


def main():
    values = config()
    environment = os.environ.copy()
    environment.update({
        "AI_SERVICE_KEY": values.get("AI_SERVICE_KEY", ""),
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": values.get("OLLAMA_MODEL", "Qwen2.5:latest"),
        "EMBEDDING_MODEL": values.get("EMBEDDING_MODEL", "bge-m3:latest"),
        "KNOWLEDGE_DATABASE_PATH": str(RUN / "knowledge.db"),
    })
    for name in ("RAG_MIN_SIMILARITY", "RAG_QUERY_REWRITE", "RAG_HYDE", "RAG_LLM_RERANK"):
        if name in values:
            environment[name] = values[name]
    return subprocess.call(
        [sys.executable, "-m", "app.knowledge_cli", *sys.argv[1:]],
        cwd=ROOT / "python-ai", env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
