import argparse
import asyncio
import json

import httpx

from .config import Settings
from .knowledge import KnowledgeStore, OllamaEmbeddings
from .retrieval import HybridRetriever


async def run(args):
    settings = Settings.from_env()
    store = KnowledgeStore(settings.knowledge_database_path)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        embeddings = OllamaEmbeddings(client, settings)
        if args.action == "sync":
            result = await store.sync(args.manifest, embeddings, semantic=args.semantic)
        elif args.action == "withdraw":
            result = store.withdraw(args.document_id)
        elif args.action == "search":
            result = await HybridRetriever(store, embeddings, client, settings).search(args.query)
        elif args.action == "evaluate":
            cases = json.loads(args.cases.read_text(encoding="utf-8"))
            rows = []
            for case in cases:
                result = await HybridRetriever(store, embeddings, client, settings).search(case["query"])
                ids = list(dict.fromkeys(c["documentId"] for c in result["citations"]))
                expected = case["expectedDocuments"]
                ranks = [i + 1 for i, did in enumerate(ids) if did in expected]
                passed = bool(ranks) if expected else not ids
                rows.append({"query": case["query"], "expectedDocuments": expected, "retrievedDocuments": ids,
                             "passed": passed, "mrr": 1 / min(ranks) if ranks else 0})
            positive = [row for row in rows if row["expectedDocuments"]]
            result = {"cases": rows, "passed": all(row["passed"] for row in rows),
                      "hitRate": sum(bool(row["mrr"]) for row in positive) / max(len(positive), 1),
                      "mrr": sum(row["mrr"] for row in positive) / max(len(positive), 1)}
            if args.output:
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            result = store.metadata()
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("passed", True) else 1


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="action", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("manifest", type=Path)
    sync.add_argument("--semantic", action="store_true")
    withdraw = commands.add_parser("withdraw")
    withdraw.add_argument("document_id")
    search = commands.add_parser("search")
    search.add_argument("query")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("cases", type=Path)
    evaluate.add_argument("--output", type=Path)
    commands.add_parser("status")
    try:
        return asyncio.run(run(parser.parse_args()))
    except Exception as exc:
        # CLI is local admin tooling; do not print document contents or model responses on error.
        print(json.dumps({"error": type(exc).__name__, "message": "知识库操作失败，现有索引未被部分替换"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
