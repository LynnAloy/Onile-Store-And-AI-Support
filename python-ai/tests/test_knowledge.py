import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np

from app.config import Settings
from app.context import fit_health
from app.errors import AppError
from app.knowledge import KnowledgeStore, OllamaEmbeddings, bounded_split, load_manifest, split_document
from app.retrieval import HybridRetriever, rrf, validate_citations


class Embeddings:
    settings = SimpleNamespace(embedding_model="test:latest")
    digest = "digest-one"
    fail = False

    def headers(self):
        return {}

    async def fingerprint(self):
        return self.digest

    async def embed(self, texts):
        if self.fail:
            raise AppError(503, "EMBEDDING_UNAVAILABLE", "unavailable")
        rows = []
        for text in texts:
            vector = np.array([1 if "钱包" in text else 0, 1 if "授权" in text else 0,
                               1 if "星球" in text else 0, .01], dtype=np.float32)
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)


class KnowledgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.entries = []
        for did, text, status in (
            ("wallet", "# 钱包规则\n钱包密码验证。钱包密码输错会锁定。", "approved"),
            ("consent", "# 授权规则\n授权需要勾选并保存。可随时撤回授权。", "approved"),
            ("pending", "# 未审核\n未审核医学材料禁止作为依据。", "pending"),
        ):
            (self.root / (did + ".md")).write_text(text, encoding="utf-8")
            self.entries.append({"id": did, "title": did, "version": "1", "file": did + ".md",
                                 "kind": "platform", "source": "local://" + did,
                                 "reviewStatus": status, "reviewer": "test", "reviewedAt": "2026-10-27"})
        self.write_manifest()
        self.store = KnowledgeStore(self.root / "kb.db")
        self.embeddings = Embeddings()
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        self.settings = Settings(service_key="x" * 32, embedding_model="test:latest")
        self.retriever = HybridRetriever(self.store, self.embeddings, self.client, self.settings)

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.entries), encoding="utf-8")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.temp.cleanup()

    async def test_pending_excluded_sync_idempotent_and_persistent(self):
        first = await self.store.sync(self.manifest, self.embeddings)
        self.assertTrue(first["updated"])
        second = await self.store.sync(self.manifest, self.embeddings)
        self.assertFalse(second["updated"])
        self.assertEqual({c["document_id"] for c in self.store.snapshot()[1]}, {"wallet", "consent"})
        self.assertEqual(KnowledgeStore(self.root / "kb.db").metadata()["revision"], 1)

    async def test_failed_rebuild_keeps_last_good_index(self):
        await self.store.sync(self.manifest, self.embeddings)
        before = self.store.snapshot()
        self.entries[0]["version"] = "2"
        self.write_manifest()
        self.embeddings.fail = True
        with self.assertRaises(AppError):
            await self.store.sync(self.manifest, self.embeddings)
        self.assertEqual(before, self.store.snapshot())

    async def test_withdrawal_invalidates_revision_and_retrieval(self):
        await self.store.sync(self.manifest, self.embeddings)
        self.assertTrue(self.store.withdraw("wallet")["withdrawn"])
        self.assertEqual(self.store.metadata()["revision"], 2)
        self.assertEqual((await self.retriever.search("钱包密码"))["citations"], [])
        self.assertFalse(self.store.withdraw("wallet")["withdrawn"])

    async def test_hybrid_parent_citations_and_dense_direction(self):
        await self.store.sync(self.manifest, self.embeddings)
        result = await self.retriever.search("钱包密码")
        self.assertEqual(result["citations"][0]["documentId"], "wallet")
        self.assertIn("# 钱包规则", result["citations"][0]["excerpt"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual((await self.retriever.search("星球卫星"))["citations"], [])

    async def test_digest_and_dimension_mismatch_fail_closed(self):
        await self.store.sync(self.manifest, self.embeddings)
        self.embeddings.digest = "new-digest"
        with self.assertRaises(AppError) as caught:
            await self.retriever.search("钱包")
        self.assertEqual(caught.exception.code, "INDEX_MODEL_MISMATCH")
        self.embeddings.digest = "digest-one"
        with self.store.connection(write=True) as conn:
            conn.execute("UPDATE chunks SET embedding=?", (np.ones(2, dtype="<f4").tobytes(),))
        with self.assertRaises(AppError):
            await self.retriever.search("钱包")

    async def test_optional_helpers_fail_back_to_original_query(self):
        await self.store.sync(self.manifest, self.embeddings)
        self.retriever.settings = self.settings.model_copy(update={
            "rag_query_rewrite": True, "rag_hyde": True, "rag_llm_rerank": True})
        result = await self.retriever.search("钱包密码和授权")
        self.assertIn("query_rewrite", result["retrieval"]["fallbacks"])
        self.assertIn("hyde", result["retrieval"]["fallbacks"])
        self.assertIn("llm_rerank", result["retrieval"]["fallbacks"])
        self.assertTrue(result["citations"])

    async def test_manifest_path_and_review_gate(self):
        self.entries[0]["file"] = "../outside.md"
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_manifest(self.manifest)
        self.entries[0]["file"] = "wallet.md"
        self.entries[0]["reviewer"] = ""
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_manifest(self.manifest)

    async def test_embedding_payload_never_truncates_and_rejects_invalid_vectors(self):
        captured = []
        for vectors in ([[0, 0]], [[float("nan"), 1]], [[1, 2], [2, 3]]):
            async def handle(request):
                captured.append(json.loads(request.content))
                return httpx.Response(200, content=json.dumps({"embeddings": vectors}))
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                with self.assertRaises(AppError):
                    await OllamaEmbeddings(client, self.settings).embed(["test"])
        self.assertTrue(all(item["truncate"] is False for item in captured))

    def test_chunk_tail_coverage_and_stable_parent_ids(self):
        text = "".join(chr(0x4e00 + i) for i in range(2000))
        parts = bounded_split(text, 300, 60)
        self.assertEqual(parts[-1][-1], text[-1])
        self.assertTrue(all(character in "".join(parts) for character in text))
        doc = {"id": "test", "version": "1", "title": "test", "text": text}
        self.assertEqual(split_document(doc), split_document(doc))
        parents, children = split_document(doc)
        self.assertTrue(all(c["parent_id"] in {p["id"] for p in parents} for c in children))

    def test_rrf_deduplicates_and_citations_must_exist(self):
        order, scores = rrf([[1, 1, 2], [2, 1]])
        self.assertEqual(set(order), {1, 2})
        self.assertAlmostEqual(scores[1], scores[2])
        validate_citations("规则[S1]", [{"id": "S1"}])
        with self.assertRaises(AppError):
            validate_citations("伪造[S2]", [{"id": "S1"}])

    def test_long_health_fields_are_omitted_whole(self):
        profile = {"heightCm": 180, "allergiesText": "无过敏。" * 500, "healthNotes": "完整备注"}
        result, omitted = fit_health(profile, 100)
        self.assertEqual(result["heightCm"], 180)
        self.assertNotIn("allergiesText", result)
        self.assertIn("allergiesText", omitted)

