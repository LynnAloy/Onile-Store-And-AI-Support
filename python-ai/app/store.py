import sqlite3
import json
import time
import uuid
from contextlib import contextmanager

from .errors import AppError


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_owner ON conversations(user_id,updated_at);
CREATE TABLE IF NOT EXISTS turns (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 conversation_id TEXT NOT NULL REFERENCES conversations(id),
 request_id TEXT NOT NULL, message TEXT NOT NULL, assistant TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL CHECK(status IN ('processing','completed','failed','interrupted')),
 error_code TEXT, created_at INTEGER NOT NULL, lease_until REAL NOT NULL,
 UNIQUE(conversation_id,request_id)
);
"""


class ConversationStore:
    def __init__(self, path):
        self.path = str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        with self.connection(write=True) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
            for name, definition in {
                "profile_revision": "INTEGER NOT NULL DEFAULT 0",
                "profile_applied": "INTEGER NOT NULL DEFAULT 0",
                "knowledge_revision": "INTEGER NOT NULL DEFAULT 0",
                "citations": "TEXT NOT NULL DEFAULT '[]'",
                "retrieval": "TEXT NOT NULL DEFAULT '{}'",
                "tool_events": "TEXT NOT NULL DEFAULT '[]'",
                "order_request_key": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in columns:
                    conn.execute("ALTER TABLE turns ADD COLUMN " + name + " " + definition)

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

    @staticmethod
    def owned(conn, user, conversation):
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation, user)
        ).fetchone()
        if row is None:
            raise AppError(404, "CONVERSATION_NOT_FOUND", "会话不存在")
        return dict(row)

    def create(self, user, title):
        cid = str(uuid.uuid4())
        now = int(time.time())
        with self.connection(write=True) as conn:
            conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (cid, user, title, now, now))
        return {"id": cid, "title": title, "createdAt": now, "updatedAt": now}

    def list(self, user):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 100",
                (user,),
            ).fetchall()
        return [{"id": r["id"], "title": r["title"], "createdAt": r["created_at"],
                 "updatedAt": r["updated_at"]} for r in rows]

    def history(self, user, conversation):
        with self.connection() as conn:
            owner = self.owned(conn, user, conversation)
            rows = conn.execute(
                "SELECT * FROM turns WHERE conversation_id=? ORDER BY sequence DESC LIMIT 100",
                (conversation,),
            ).fetchall()
        now = time.time()
        turns = []
        for row in reversed(rows):
            state = row["status"]
            if state == "processing" and row["lease_until"] <= now:
                state = "interrupted"
            turns.append({"requestId": row["request_id"], "message": row["message"],
                          "assistant": row["assistant"], "status": state,
                          "errorCode": row["error_code"], "createdAt": row["created_at"],
                          "personalizationApplied": bool(row["profile_applied"]),
                          "profileRevision": row["profile_revision"],
                          "citations": json.loads(row["citations"]),
                          "retrieval": json.loads(row["retrieval"]),
                          "toolEvents": json.loads(row["tool_events"])})
        return {"id": conversation, "title": owner["title"], "turns": turns}

    def start(self, user, conversation, request_id, message, lease_seconds,
              profile_revision=0, profile_applied=False, knowledge_revision=0, order_request_key=""):
        with self.connection(write=True) as conn:
            self.owned(conn, user, conversation)
            now = time.time()
            conn.execute(
                "UPDATE turns SET status='interrupted',error_code='SERVER_INTERRUPTED' "
                "WHERE conversation_id=? AND status='processing' AND lease_until<=?", (conversation, now),
            )
            previous = conn.execute(
                "SELECT * FROM turns WHERE conversation_id=? AND request_id=?",
                (conversation, request_id),
            ).fetchone()
            if previous:
                if previous["order_request_key"] != order_request_key:
                    raise AppError(409, "ORDER_INTENT_CHANGED", "本次订单准备授权已变化，请使用新请求ID")
                if previous["message"] != message:
                    raise AppError(409, "IDEMPOTENCY_CONFLICT", "相同请求ID不能对应不同消息")
                if (previous["profile_revision"], bool(previous["profile_applied"]), previous["knowledge_revision"]) != (
                    profile_revision, profile_applied, knowledge_revision
                ):
                    raise AppError(409, "CONTEXT_CHANGED", "资料授权或知识库已改变，请使用新请求ID")
                if previous["status"] == "completed":
                    return {"replay": True, "assistant": previous["assistant"],
                            "binding": {"enabled": profile_applied, "revision": profile_revision},
                            "knowledgeRevision": knowledge_revision,
                            "metadata": {"citations": json.loads(previous["citations"]),
                                         "retrieval": json.loads(previous["retrieval"]),
                                         "personalizationApplied": bool(previous["profile_applied"]),
                                         "profileRevision": previous["profile_revision"]},
                            "toolEvents": json.loads(previous["tool_events"])}
                code = "TURN_IN_PROGRESS" if previous["status"] == "processing" else "TURN_NOT_REPLAYABLE"
                raise AppError(409, code, "该请求正在执行或已中断，请刷新会话后重试")
            busy = conn.execute(
                "SELECT 1 FROM turns WHERE conversation_id=? AND status='processing'", (conversation,)
            ).fetchone()
            if busy:
                raise AppError(409, "CONVERSATION_BUSY", "当前会话正在生成回答")
            active = conn.execute(
                "SELECT COUNT(*) FROM turns t JOIN conversations c ON c.id=t.conversation_id "
                "WHERE c.user_id=? AND t.status='processing' AND t.lease_until>?", (user, now),
            ).fetchone()[0]
            if active >= 2:
                raise AppError(429, "TOO_MANY_ACTIVE_TURNS", "同时生成的会话过多，请稍后重试")
            conn.execute(
                "INSERT INTO turns(conversation_id,request_id,message,status,created_at,lease_until) "
                "VALUES (?,?,?,'processing',?,?)",
                (conversation, request_id, message, int(now), now + lease_seconds),
            )
            conn.execute("UPDATE turns SET profile_revision=?,profile_applied=?,knowledge_revision=? "
                         "WHERE conversation_id=? AND request_id=?",
                         (profile_revision, int(profile_applied), knowledge_revision, conversation, request_id))
            conn.execute("UPDATE turns SET order_request_key=? WHERE conversation_id=? AND request_id=?",
                         (order_request_key, conversation, request_id))
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (int(now), conversation))
        return {"replay": False, "binding": {"enabled": profile_applied, "revision": profile_revision},
                "knowledgeRevision": knowledge_revision}

    def context(self, user, conversation, message, turn_limit, char_limit,
                profile_revision=None, knowledge_revision=0):
        with self.connection() as conn:
            self.owned(conn, user, conversation)
            rows = conn.execute(
                "SELECT message,assistant,tool_events FROM turns WHERE conversation_id=? AND status='completed' "
                "AND (profile_applied=0 OR (? IS NOT NULL AND profile_revision=?)) "
                "AND (knowledge_revision=0 OR knowledge_revision=?) "
                "ORDER BY sequence DESC LIMIT ?",
                (conversation, profile_revision, profile_revision, knowledge_revision, turn_limit),
            ).fetchall()
        pairs = []
        budget = char_limit - len(message)
        for row in rows:
            assistant = row["assistant"]
            if json.loads(row["tool_events"]):
                # Prior tool-backed prose can contain stale prices or order states. Keep only references.
                references = []
                for item in json.loads(row["tool_events"]):
                    result = item["data"].get("result", {})
                    references.extend({"medicineId": p["id"], "name": p["name"]}
                                      for p in result.get("products", []))
                    if result.get("order"):
                        references.append({"orderId": result["order"]["orderId"]})
                    if result.get("draft"):
                        references.append({"draftId": result["draft"]["draftId"]})
                    references.extend({"medicineId": product["id"], "name": product["name"]}
                                      for product in result.get("proposal", {}).get("items", []))
                assistant = "历史查询仅保留标识；价格、库存和订单状态必须重新调用工具查询：" + json.dumps(references, ensure_ascii=False)
            size = len(row["message"]) + len(assistant)
            if size > budget:
                break
            budget -= size
            pairs.append([{"role": "user", "content": row["message"]},
                          {"role": "assistant", "content": assistant}])
        result = [entry for pair in reversed(pairs) for entry in pair]
        return result + [{"role": "user", "content": message}]

    def attach_metadata(self, conversation, request_id, metadata):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE turns SET citations=?,retrieval=? WHERE conversation_id=? AND request_id=?",
                         (json.dumps(metadata["citations"], ensure_ascii=False),
                          json.dumps(metadata["retrieval"]), conversation, request_id))

    def finish(self, conversation, request_id, content, status, error=None):
        with self.connection(write=True) as conn:
            conn.execute(
                "UPDATE turns SET assistant=?,status=?,error_code=? "
                "WHERE conversation_id=? AND request_id=? AND status='processing'",
                (content, status, error, conversation, request_id),
            )

    def append_tool_event(self, conversation, request_id, value):
        with self.connection(write=True) as conn:
            row = conn.execute("SELECT tool_events FROM turns WHERE conversation_id=? AND request_id=?",
                               (conversation, request_id)).fetchone()
            events = json.loads(row[0])
            if len(events) >= 12:
                raise AppError(502, "TOOL_CALL_LIMIT", "工具轨迹达到上限")
            events.append(value)
            conn.execute("UPDATE turns SET tool_events=? WHERE conversation_id=? AND request_id=?",
                         (json.dumps(events, ensure_ascii=False), conversation, request_id))
