"""Versioned public knowledge only. Patient profiles must never enter this database."""
import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np

from .errors import AppError


SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_meta (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL DEFAULT 0,
 corpus_hash TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
 model_digest TEXT NOT NULL DEFAULT '', dimension INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO knowledge_meta(id) VALUES (1);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, version TEXT NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL,
 kind TEXT NOT NULL, review_status TEXT NOT NULL, reviewer TEXT NOT NULL,
 reviewed_at TEXT NOT NULL, active INTEGER NOT NULL, content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parents (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 heading TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, parent_id TEXT NOT NULL REFERENCES parents(id),
 document_id TEXT NOT NULL REFERENCES documents(id), text TEXT NOT NULL, embedding BLOB NOT NULL
);
"""


def stable_id(*parts):
    return hashlib.sha256("\n".join(str(part) for part in parts).encode()).hexdigest()[:32]


def tokenize(text):
    stop = {"怎么", "什么", "如何", "可以", "是否", "我的", "你的", "一个", "哪些",
            "请问", "需要", "问题", "多少", "进行", "使用", "用于", "有关", "以及",
            "the", "is", "a", "an", "to", "of", "and"}
    words = []
    for token in re.findall(r"[a-zA-Z0-9_-]+|[\u4e00-\u9fff]+", text.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            words.extend(token[i:i + 2] for i in range(max(len(token) - 1, 0)))
        else:
            words.append(token)
    return [word for word in words if word not in stop]


def bounded_split(text, maximum, overlap=0, preferred=()):
    if not 0 <= overlap < maximum:
        raise ValueError("Invalid chunk overlap")
    result = []
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            candidates = [point for point in preferred if start + maximum // 2 < point <= end]
            candidates += [match.end() + start for match in
                           re.finditer(r"[。！？\n]", text[start:end])
                           if match.end() > maximum // 2]
            if candidates:
                end = max(candidates)
        part = text[start:end].strip()
        if part:
            result.append(part)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return result


def split_document(document, boundaries=None):
    parents, children = [], []
    sections = re.split(r"(?m)(?=^#{1,3} )", document["text"])
    for section in sections:
        heading = section.splitlines()[0][:160] if section.strip() else document["title"]
        for text in bounded_split(section, 1200):
            pid = stable_id(document["id"], document["version"], len(parents), text)
            parents.append({"id": pid, "document_id": document["id"], "heading": heading, "text": text})
            preferred = boundaries.get(text, ()) if boundaries else ()
            for index, child in enumerate(bounded_split(text, 300, 60, preferred)):
                children.append({"id": stable_id(pid, index, child), "parent_id": pid,
                                 "document_id": document["id"], "text": child})
    return parents, children


def load_manifest(path):
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) > 200:
        raise ValueError("Manifest must contain at most 200 documents")
    documents, seen = [], set()
    for entry in raw:
        allowed = {"id", "version", "title", "source", "kind", "reviewStatus", "reviewer",
                   "reviewedAt", "file"}
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise ValueError("Unsupported manifest fields")
        did = entry.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", did) or did in seen:
            raise ValueError("Document IDs must be unique and stable")
        seen.add(did)
        target = (path.parent / entry["file"]).resolve()
        if not target.is_relative_to(path.parent) or target.suffix.lower() not in (".md", ".txt"):
            raise ValueError("Only text/Markdown files inside the manifest directory may be indexed")
        text = target.read_text(encoding="utf-8").strip()
        if not text or len(text) > 100000:
            raise ValueError("Document text must contain 1..100000 characters")
        source = entry.get("source", "")
        if urlsplit(source).scheme not in ("http", "https", "local"):
            raise ValueError("Unsupported citation source URI")
        if entry.get("kind") not in ("platform", "medical"):
            raise ValueError("Document kind must be platform or medical")
        status = entry.get("reviewStatus", "pending")
        if status not in ("pending", "approved", "withdrawn"):
            raise ValueError("Unsupported review status")
        if not entry.get("version") or len(entry["version"]) > 40 or not entry.get("title"):
            raise ValueError("Document title and version are required")
        if status == "approved" and (not entry.get("reviewer") or not entry.get("reviewedAt")):
            raise ValueError("Approved documents require an explicit reviewer and review date")
        documents.append({
            "id": did, "version": entry["version"], "title": entry["title"][:200],
            "source": source, "kind": entry["kind"], "review_status": status,
            "reviewer": entry.get("reviewer", ""), "reviewed_at": entry.get("reviewedAt", ""),
            "active": int(status == "approved"), "content_hash": stable_id(text), "text": text,
        })
    return documents


class OllamaEmbeddings:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    def headers(self):
        key = self.settings.model_api_key
        return {"Authorization": "Bearer " + key} if key else {}

    async def fingerprint(self):
        try:
            response = await self.client.get(
                self.settings.ollama_base_url + "/api/tags", headers=self.headers(), timeout=5,
            )
            response.raise_for_status()
            model = self.settings.embedding_model.casefold()
            if ":" not in model:
                model += ":latest"
            match = next(item for item in response.json()["models"] if item["name"].casefold() == model)
            return match["digest"]
        except (httpx.HTTPError, KeyError, ValueError, TypeError, StopIteration):
            raise AppError(503, "EMBEDDING_UNAVAILABLE", "嵌入模型不可用，请检查本机模型配置") from None

    async def embed(self, texts):
        try:
            response = await self.client.post(
                self.settings.ollama_base_url + "/api/embed",
                json={"model": self.settings.embedding_model, "input": texts, "truncate": False},
                headers=self.headers(), timeout=self.settings.embedding_timeout,
            )
            response.raise_for_status()
            vectors = np.asarray(response.json()["embeddings"], dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(texts) or vectors.shape[1] < 1:
                raise ValueError("Unexpected vector shape")
            norms = np.linalg.norm(vectors, axis=1)
            if not np.isfinite(vectors).all() or not np.isfinite(norms).all() or np.any(norms == 0):
                raise ValueError("Invalid embedding values")
            return vectors / norms[:, None]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AppError(503, "EMBEDDING_UNAVAILABLE", "嵌入计算失败，索引未更新") from None


class KnowledgeStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    def metadata(self):
        with self.connection() as conn:
            return dict(conn.execute("SELECT * FROM knowledge_meta WHERE id=1").fetchone())

    def snapshot(self):
        with self.connection() as conn:
            conn.execute("BEGIN")
            meta = dict(conn.execute("SELECT * FROM knowledge_meta WHERE id=1").fetchone())
            rows = conn.execute(
                "SELECT c.*,p.text AS parent_text,p.heading,d.version,d.title,d.source,d.kind "
                "FROM chunks c JOIN parents p ON c.parent_id=p.id "
                "JOIN documents d ON d.id=c.document_id WHERE d.active=1 AND d.review_status='approved'"
            ).fetchall()
        return meta, [dict(row) for row in rows]

    async def sync(self, manifest, embeddings, semantic=False):
        documents = load_manifest(manifest)
        digest = await embeddings.fingerprint()
        fingerprint = stable_id(json.dumps(documents, sort_keys=True, ensure_ascii=False),
                                embeddings.settings.embedding_model, digest, semantic, "chunks-v1")
        previous = self.metadata()
        if previous["corpus_hash"] == fingerprint:
            return {"updated": False, "revision": previous["revision"]}
        parents, children = [], []
        for document in documents:
            if not document["active"]:
                continue
            doc_parents, doc_children = split_document(document)
            if semantic:
                boundaries = {}
                for parent in doc_parents:
                    sentences = re.findall(r"[^。！？\n]+[。！？\n]*", parent["text"])
                    if len(sentences) > 1:
                        vectors = await embeddings.embed(sentences)
                        offset, points = 0, []
                        for index, sentence in enumerate(sentences):
                            if index and float(vectors[index - 1] @ vectors[index]) < 0.55:
                                points.append(offset)
                            offset += len(sentence)
                        boundaries[parent["text"]] = points
                doc_parents, doc_children = split_document(document, boundaries)
            parents.extend(doc_parents)
            children.extend(doc_children)
        if len(children) > 10000:
            raise ValueError("This exact-search index supports at most 10000 chunks")
        vectors = []
        for offset in range(0, len(children), 8):
            batch = await embeddings.embed([c["text"] for c in children[offset:offset + 8]])
            vectors.extend(batch)
        dimension = len(vectors[0]) if vectors else 0
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("Embedding dimension changed during indexing")
        if await embeddings.fingerprint() != digest:
            raise ValueError("Embedding model changed during indexing; retry with a stable model")
        # Build outside the transaction. Replace the complete index atomically, preserving old reads on failure.
        with self.connection(write=True) as conn:
            current = conn.execute("SELECT revision FROM knowledge_meta WHERE id=1").fetchone()[0]
            if current != previous["revision"]:
                raise ValueError("Another index update completed first; retry")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM parents")
            conn.execute("DELETE FROM documents")
            for doc in documents:
                conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
                             tuple(doc[key] for key in ("id", "version", "title", "source", "kind",
                                                       "review_status", "reviewer", "reviewed_at",
                                                       "active", "content_hash")))
            for parent in parents:
                conn.execute("INSERT INTO parents VALUES (?,?,?,?)",
                             (parent["id"], parent["document_id"], parent["heading"], parent["text"]))
            for child, vector in zip(children, vectors):
                conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?)",
                             (child["id"], child["parent_id"], child["document_id"], child["text"],
                              np.asarray(vector, dtype="<f4").tobytes()))
            conn.execute("UPDATE knowledge_meta SET revision=?,corpus_hash=?,model=?,model_digest=?,dimension=? "
                         "WHERE id=1", (current + 1, fingerprint, embeddings.settings.embedding_model,
                                       digest, dimension))
        return {"updated": True, "revision": current + 1, "documents": len(documents),
                "parents": len(parents), "chunks": len(children), "dimension": dimension}

    def withdraw(self, document_id):
        with self.connection(write=True) as conn:
            changed = conn.execute("UPDATE documents SET active=0,review_status='withdrawn' "
                                   "WHERE id=? AND active=1", (document_id,)).rowcount
            if changed:
                conn.execute("UPDATE knowledge_meta SET revision=revision+1,corpus_hash='' WHERE id=1")
        return {"withdrawn": bool(changed), "revision": self.metadata()["revision"]}


def bm25_scores(query, chunks):
    terms = set(tokenize(query))
    if not terms or not chunks:
        return []
    corpus = [Counter(tokenize(chunk["text"])) for chunk in chunks]
    lengths = [sum(doc.values()) for doc in corpus]
    average = sum(lengths) / max(len(lengths), 1) or 1
    frequencies = {term: sum(term in doc for doc in corpus) for term in terms}
    scores = []
    for index, document in enumerate(corpus):
        score, overlap = 0.0, 0
        for term in terms:
            tf = document.get(term, 0)
            if not tf:
                continue
            overlap += 1
            idf = math.log(1 + (len(corpus) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            denominator = tf + 1.5 * (0.25 + 0.75 * lengths[index] / average)
            score += idf * tf * 2.5 / denominator
        if overlap >= 2 and score > 0:
            scores.append((index, score))
    return sorted(scores, key=lambda item: (-item[1], item[0]))
