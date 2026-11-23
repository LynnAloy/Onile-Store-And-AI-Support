import asyncio
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.config import Settings
from app.errors import AppError
from app.main import create_app, stream_turn


ALICE = "a" * 43
BOB = "b" * 43
ORDER = "o" * 43
SERVICE_KEY = "test-service-key-at-least-32-characters"


def frames(*contents, done=True):
    values = [{"message": {"role": "assistant", "content": value}, "done": False} for value in contents]
    if done:
        values.append({"message": {"content": ""}, "done": True})
    return b"".join(json.dumps(item, ensure_ascii=False).encode() + b"\n" for item in values)


def events(response):
    parsed = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        kind = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if kind and data:
            parsed.append((kind, json.loads(data)))
    return parsed


class AIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mode = "normal"
        self.identity_mode = "normal"
        self.revoked = False
        self.profile_enabled = False
        self.profile_revision = 0
        self.order_enabled = True
        self.order_key = str(uuid.uuid4())
        self.order_expires = int(time.time()) + 300
        self.order_mode = "normal"
        self.order_items = [{"medicineId": 1, "quantity": 2}]
        self.health_profile = {"heightCm": 180, "weightKg": 72, "medicalHistoryText": "合成测试病史"}
        self.java_requests = []
        self.model_requests = []
        self.settings = Settings(
            service_key=SERVICE_KEY, database_path=Path(self.temp.name) / "ai.db",
            model_timeout=1,
            knowledge_database_path=Path(self.temp.name) / "knowledge.db",
        )

        async def java(request):
            self.java_requests.append(request)
            if self.identity_mode == "offline":
                raise httpx.ConnectError("sensitive connection details", request=request)
            if self.identity_mode == "invalid":
                return httpx.Response(200, json=[])
            if self.identity_mode == "error":
                return httpx.Response(500, text="sensitive details")
            if request.headers.get("X-AI-Service-Key") != SERVICE_KEY or self.revoked:
                return httpx.Response(401)
            token = request.headers.get("Authorization", "")[7:]
            if token not in (ALICE, BOB, ORDER, "u" * 43):
                return httpx.Response(401)
            if request.url.path.endswith("/order-preparation"):
                if token != ORDER or not self.order_enabled:
                    return httpx.Response(401)
                return httpx.Response(200, json={"scope": "AGENT_ORDER_PREPARE", "userId": "alice",
                    "items": self.order_items, "requestKey": self.order_key, "expiresAt": self.order_expires})
            if request.url.path.endswith("/order-drafts"):
                if token != ORDER or not self.order_enabled:
                    return httpx.Response(401)
                if self.order_mode == "timeout":
                    raise httpx.ReadTimeout("private connection details")
                if self.order_mode == "malformed":
                    return httpx.Response(409, json=[])
                return httpx.Response(200, json={"draftId": "draft-test-1", "paid": self.order_mode == "paid",
                    "status": "PREPARED", "version": 1, "totalPrice": "24.60", "currency": "CNY",
                    "expiresAt": int(time.time()) + 900, "recipientPhone": "private-phone",
                    "items": [{"medicineId": 1, "quantity": 2, "name": "合成商品", "price": "12.30"}]})
            if request.url.path.endswith("/medicines"):
                return httpx.Response(200, json=[{"id": 1, "name": "合成商品", "price": 12.30, "stock": 0}])
            if "/orders/" in request.url.path:
                return httpx.Response(404)
            if request.url.path.endswith(("personalization-status", "personalization-context")):
                data = {"enabled": self.profile_enabled and token == ALICE, "revision": self.profile_revision}
                if request.url.path.endswith("personalization-context") and data["enabled"]:
                    data["profile"] = self.health_profile
                return httpx.Response(200, json=data)
            return httpx.Response(200, json={
                "userId": "alice" if token == ALICE else "bob",
                "scope": "USER" if token == "u" * 43 else "AGENT_ORDER_PREPARE" if token == ORDER else "AGENT_READ",
            })

        async def model(request):
            self.model_requests.append(request)
            if self.mode == "unsupported-tools":
                return httpx.Response(400, text="private model details")
            if self.mode == "bad-tool-packet":
                return httpx.Response(200, json={"message": {"tool_calls": "invalid"}, "done": True})
            if self.mode.startswith("tool-"):
                payload = json.loads(request.content)
                if self.mode == "tool-proposal" and payload["messages"][-1].get("tool_name") == "search_medicines":
                    return httpx.Response(200, json={"message": {"tool_calls": [{"function": {
                        "name": "propose_purchase", "arguments": {"items": [{"medicineId": 1,
                        "quantity": 5, "evidence": "5件合成商品"}]}}}]}, "done": True})
                if payload["messages"][-1]["role"] == "tool" and self.mode != "tool-loop" and not (
                        self.mode == "tool-draft-repeat" and len(self.model_requests) == 2):
                    return httpx.Response(200, content=frames("查询结束，请核对查询卡片。"))
                name, args = "search_medicines", {"name": "合成商品"}
                if self.mode == "tool-invalid":
                    args["userId"] = "bob"
                if self.mode == "tool-repair" and len(self.model_requests) == 1:
                    args["limit"] = "5"
                if self.mode == "tool-unknown":
                    name = "pay_order"
                if self.mode == "tool-order":
                    name, args = "get_my_order", {"orderId": "ORD_other"}
                if self.mode.startswith("tool-draft"):
                    name, args = "prepare_order_draft", {"items": [{"medicineId": 1, "quantity": 2}]}
                    if self.mode == "tool-draft-mismatch":
                        args["items"][0]["quantity"] = 99
                    if self.mode == "tool-draft-revoke":
                        self.order_enabled = False
                data = {"message": {"content": "准备查询。" if self.mode == "tool-repair" else "", "tool_calls": [
                    {"function": {"name": name, "arguments": args}}]}, "done": True}
                return httpx.Response(200, content=json.dumps(data).encode() + b"\n")
            if self.mode == "slow":
                await asyncio.Event().wait()
            if self.mode == "status":
                return httpx.Response(500, text="sensitive model details")
            if self.mode == "network":
                raise httpx.ConnectError("private endpoint details", request=request)
            if self.mode == "read-timeout":
                raise httpx.ReadTimeout("private timeout details", request=request)
            if self.mode == "invalid":
                return httpx.Response(200, content=b"not-json\n")
            if self.mode == "bad-content":
                return httpx.Response(200, content=b'{"message":{"content":123},"done":true}\n')
            if self.mode == "truncated":
                return httpx.Response(200, content=frames("部分回答", done=False))
            if self.mode == "empty":
                return httpx.Response(200, content=frames())
            if self.mode == "thinking":
                return httpx.Response(200, content=(
                    b'{"message":{"thinking":"private-reasoning","content":""},"done":false}\n'
                    + frames("公开回答")))
            if self.mode == "oversize":
                return httpx.Response(200, content=b"x" * 65537)
            if self.mode == "revoke":
                self.revoked = True
            if self.mode == "revoke-profile":
                self.profile_enabled = False
                self.profile_revision += 1
            return httpx.Response(200, content=frames("你好", "，已收到。"))

        self.app = create_app(
            self.settings, java_transport=httpx.MockTransport(java),
            model_transport=httpx.MockTransport(model),
        )
        self.lifecycle = self.app.router.lifespan_context(self.app)
        await self.lifecycle.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifecycle.__aexit__(None, None, None)
        self.temp.cleanup()

    async def request(self, method, path, token=ALICE, **kwargs):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return await self.client.request(method, path, headers=headers, **kwargs)

    async def create(self, token=ALICE):
        response = await self.request("POST", "/ai/v1/conversations", token, json={"title": "测试会话"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    async def send(self, conversation, message="你好", request_id=None, token=ALICE):
        return await self.request(
            "POST", f"/ai/v1/conversations/{conversation}/messages", token,
            json={"requestId": request_id or str(uuid.uuid4()), "message": message},
        )

    async def history(self, conversation, token=ALICE):
        return await self.request("GET", f"/ai/v1/conversations/{conversation}/messages", token)

    async def test_health_and_protected_routes(self):
        self.assertEqual((await self.client.get("/ai/health")).status_code, 200)
        for token in (None, "mock_token", "u" * 43, "x" * 43):
            result = await self.request("GET", "/ai/v1/conversations", token)
            self.assertEqual(result.status_code, 401)
        self.assertEqual((await self.client.get("/missing")).status_code, 404)

    async def test_disabled_profile_never_fetches_details(self):
        conversation = await self.create()
        await self.send(conversation)
        self.assertFalse(any(r.url.path.endswith("personalization-context") for r in self.java_requests))
        self.assertNotIn("合成测试病史", self.model_requests[-1].content.decode())

    async def test_real_tool_protocol_round_trip_persistence_and_replay(self):
        self.mode = "tool-search"
        conversation = await self.create()
        rid = str(uuid.uuid4())
        result = await self.send(conversation, "查询商品", rid)
        parsed = events(result)
        self.assertEqual([kind for kind, data in parsed],
                         ["start", "context", "tool_started", "tool_result", "delta", "done"])
        tool = next(data for kind, data in parsed if kind == "tool_result")
        self.assertEqual(tool["result"]["products"][0]["price"], "12.30")
        self.assertEqual(tool["result"]["products"][0]["stock"], 0)
        request = next(r for r in self.java_requests if r.url.path.endswith("/medicines"))
        self.assertEqual(request.headers["Authorization"], "Bearer " + ALICE)
        self.assertEqual(request.headers["X-Request-ID"], tool["callId"])
        history = (await self.history(conversation)).json()["turns"][0]
        self.assertEqual(len(history["toolEvents"]), 2)
        count = len(self.model_requests)
        requests = len([r for r in self.java_requests if r.url.path.endswith("/medicines")])
        replay = await self.send(conversation, "查询商品", rid)
        self.assertEqual(events(replay)[-1][0], "done")
        self.assertEqual(len(self.model_requests), count)
        self.assertEqual(len([r for r in self.java_requests if r.url.path.endswith("/medicines")]), requests)
        prompt = json.loads(self.model_requests[-1].content)
        self.assertEqual(prompt["messages"][-1]["role"], "tool")
        self.assertNotIn(SERVICE_KEY, self.model_requests[-1].content.decode())
        with self.app.state.store.connection(write=True) as conn:
            conn.execute("UPDATE turns SET assistant='旧价999不应再次使用' WHERE conversation_id=?", (conversation,))
        context = self.app.state.store.context("alice", conversation, "重新查", 10, 6000)
        self.assertNotIn("旧价999", json.dumps(context, ensure_ascii=False))
        self.assertIn("medicineId", json.dumps(context))

    async def test_invalid_or_unknown_tools_never_reach_business_api(self):
        for mode in ("tool-invalid", "tool-unknown"):
            self.mode = mode
            result = await self.send(await self.create())
            self.assertEqual(events(result)[-1][1]["code"], "INVALID_TOOL_CALL")
        self.assertFalse(any(r.url.path.endswith("/medicines") for r in self.java_requests))

    async def test_one_protocol_repair_then_actual_validated_query(self):
        self.mode = "tool-repair"
        result = await self.send(await self.create())
        self.assertEqual(events(result)[-1][0], "done")
        self.assertEqual(len(self.model_requests), 3)
        self.assertEqual(sum(r.url.path.endswith("/medicines") for r in self.java_requests), 1)
        messages = json.loads(self.model_requests[-1].content)["messages"]
        called = next(item for item in messages if item.get("tool_calls"))
        self.assertEqual(called["content"], "")

    async def test_replay_preserves_nonzero_profile_and_knowledge_bindings(self):
        self.profile_enabled = True
        self.profile_revision = 4
        with self.app.state.knowledge.connection(write=True) as conn:
            conn.execute("UPDATE knowledge_meta SET revision=3 WHERE id=1")
        conversation = await self.create()
        rid = str(uuid.uuid4())
        await self.send(conversation, "回放检查", rid)
        result = await self.send(conversation, "回放检查", rid)
        self.assertEqual(events(result)[-1][0], "done")
        self.assertTrue(events(result)[-1][1]["replayed"])
        self.assertEqual(len(self.model_requests), 1)

    async def test_unsupported_and_malformed_tool_protocols_fail_explicitly(self):
        for mode, expected in (("unsupported-tools", "MODEL_TOOLS_UNAVAILABLE"),
                               ("bad-tool-packet", "MODEL_TOOL_PROTOCOL_ERROR")):
            self.mode = mode
            result = await self.send(await self.create())
            self.assertEqual(events(result)[-1][1]["code"], expected)
            self.assertNotIn("private model details", result.text)

    async def test_missing_order_is_controlled_tool_failure(self):
        self.mode = "tool-order"
        result = await self.send(await self.create())
        data = next(data for kind, data in events(result) if kind == "tool_result")
        self.assertFalse(data["result"]["ok"])
        self.assertEqual(data["result"]["code"], "NOT_FOUND")
        self.assertEqual(events(result)[-1][0], "done")

    async def test_proposal_preserves_quantity_in_sse_and_history_without_order_authorization(self):
        self.mode = "tool-proposal"
        cid = await self.create()
        result = await self.send(cid, "帮我下单5件合成商品")
        self.assertEqual(events(result)[-1][0], "done")
        proposal = next(data["result"]["proposal"] for kind, data in events(result)
                        if kind == "tool_result" and data["tool"] == "propose_purchase")
        self.assertEqual(proposal["items"][0]["quantity"], 5)
        self.assertFalse(proposal["items"][0]["draftEligible"])
        self.assertFalse(any(r.method == "POST" for r in self.java_requests))
        history = (await self.history(cid)).json()["turns"][0]["toolEvents"]
        self.assertTrue(any(item["data"].get("result", {}).get("proposal") == proposal for item in history))

    async def send_draft(self, conversation, token=ALICE, order_token=ORDER, items=None, request_id=None):
        headers = {"Authorization": "Bearer " + token}
        if order_token:
            headers["X-Order-Agent-Token"] = order_token
        return await self.client.post(f"/ai/v1/conversations/{conversation}/messages", headers=headers,
            json={"message": "明确授权准备指定商品草稿", "requestId": request_id or str(uuid.uuid4()),
                  "purchaseIntent": {"items": items or self.order_items}})

    async def test_draft_tool_requires_separate_intent_bound_grant_and_strips_private_fields(self):
        self.mode = "tool-draft"
        cid = await self.create()
        result = await self.send_draft(cid)
        parsed = events(result)
        self.assertEqual(parsed[-1][0], "done")
        draft = next(data for kind, data in parsed if kind == "tool_result")["result"]["draft"]
        self.assertFalse(draft["paid"])
        self.assertNotIn("recipientPhone", draft)
        write = next(r for r in self.java_requests if r.method == "POST")
        self.assertEqual(write.headers["Authorization"], "Bearer " + ORDER)
        self.assertEqual(write.headers["Idempotency-Key"], self.order_key)
        for request in self.model_requests:
            self.assertNotIn(ORDER, request.content.decode())
            self.assertNotIn("private-phone", request.content.decode())
        self.assertNotIn(ORDER.encode(), Path(self.app.state.store.path).read_bytes())

    async def test_draft_tool_not_advertised_or_executed_without_authorization(self):
        self.mode = "tool-draft"
        result = await self.send(await self.create())
        self.assertEqual(events(result)[-1][1]["code"], "ORDER_AUTHORIZATION_REQUIRED")
        self.assertFalse(any(r.method == "POST" for r in self.java_requests))
        schemas = json.loads(self.model_requests[0].content)["tools"]
        self.assertNotIn("prepare_order_draft", [s["function"]["name"] for s in schemas])

    async def test_draft_missing_grant_cross_user_or_changed_items_cannot_write(self):
        cid = await self.create()
        self.assertEqual((await self.send_draft(cid, order_token=None)).status_code, 400)
        bob = await self.create(BOB)
        self.assertEqual((await self.send_draft(bob, token=BOB)).status_code, 403)
        self.assertEqual((await self.send_draft(cid, items=[{"medicineId": 1, "quantity": 3}])).status_code, 403)
        self.assertFalse(any(r.method == "POST" for r in self.java_requests))

    async def test_model_cannot_change_authorized_items(self):
        self.mode = "tool-draft-mismatch"
        result = await self.send_draft(await self.create())
        self.assertEqual(events(result)[-1][1]["code"], "ORDER_INTENT_MISMATCH")
        self.assertFalse(any(r.method == "POST" for r in self.java_requests))

    async def test_revoked_order_grant_stops_before_write(self):
        self.mode = "tool-draft-revoke"
        result = await self.send_draft(await self.create())
        self.assertEqual(events(result)[-1][1]["code"], "ORDER_AUTHORIZATION_INVALID")
        self.assertFalse(any(r.method == "POST" for r in self.java_requests))

    async def test_ambiguous_draft_response_not_automatically_retried(self):
        self.mode = "tool-draft-repeat"
        self.order_mode = "timeout"
        result = await self.send_draft(await self.create())
        self.assertEqual(events(result)[-1][0], "done")
        results = [data["result"] for kind, data in events(result) if kind == "tool_result"]
        self.assertTrue(all(r["code"] == "DRAFT_OUTCOME_UNKNOWN" for r in results))
        self.assertEqual(sum(r.method == "POST" for r in self.java_requests), 1)

    async def test_malformed_or_paid_draft_snapshot_is_not_trusted(self):
        self.mode = "tool-draft"
        for mode in ("malformed", "paid"):
            self.order_mode = mode
            result = await self.send_draft(await self.create())
            data = next(data for kind, data in events(result) if kind == "tool_result")
            self.assertEqual(data["result"]["code"], "DRAFT_OUTCOME_UNKNOWN")
            self.assertNotIn("draft", data["result"])

    async def test_draft_grant_change_blocks_same_request_replay(self):
        self.mode = "tool-draft"
        cid = await self.create()
        rid = str(uuid.uuid4())
        await self.send_draft(cid, request_id=rid)
        self.order_key = str(uuid.uuid4())
        result = await self.send_draft(cid, request_id=rid)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["code"], "ORDER_INTENT_CHANGED")

    async def test_tool_loop_is_bounded(self):
        self.mode = "tool-loop"
        result = await self.send(await self.create())
        parsed = events(result)
        self.assertEqual(parsed[-1][1]["code"], "TOOL_CALL_LIMIT")
        self.assertEqual(sum(kind == "tool_result" for kind, data in parsed), 3)

    async def test_revocation_after_tool_started_prevents_business_call(self):
        self.mode = "tool-search"
        conversation = await self.create()
        rid = str(uuid.uuid4())
        prepared = self.app.state.store.start("alice", conversation, rid, "查询", 60)
        async def connected():
            return False
        generator = stream_turn(self.app, conversation, rid, "查询", "alice", ALICE, prepared, connected)
        for expected in ("start", "context", "tool_started"):
            self.assertIn("event: " + expected, await anext(generator))
        self.revoked = True
        # Execute itself uses the short-lived delegation; Java rejects revoked credentials.
        frame = await anext(generator)
        self.assertIn("UNAUTHORIZED", frame)
        await generator.aclose()

    async def test_authorized_profile_is_whitelisted_and_isolated(self):
        self.profile_enabled = True
        self.profile_revision = 1
        self.health_profile["phoneNum"] = "private-phone"
        conversation = await self.create()
        result = await self.send(conversation)
        context = next(data for kind, data in events(result) if kind == "context")
        self.assertTrue(context["personalizationApplied"])
        prompt = json.loads(self.model_requests[-1].content)["messages"][0]["content"]
        self.assertIn("合成测试病史", prompt)
        self.assertNotIn("private-phone", prompt)
        bob = await self.create(BOB)
        await self.send(bob, token=BOB)
        self.assertNotIn("合成测试病史", json.loads(self.model_requests[-1].content)["messages"][0]["content"])
        # No health snapshot is persisted in either SQLite database.
        self.assertNotIn("合成测试病史".encode(), Path(self.app.state.store.path).read_bytes())
        self.assertEqual(self.app.state.knowledge.snapshot()[1], [])

    async def test_revocation_excludes_personalized_history_and_blocks_replay(self):
        self.profile_enabled = True
        self.profile_revision = 1
        conversation = await self.create()
        rid = str(uuid.uuid4())
        await self.send(conversation, "先前个性化提问", rid)
        self.profile_enabled = False
        self.profile_revision += 1
        replay = await self.send(conversation, "先前个性化提问", rid)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["code"], "CONTEXT_CHANGED")
        await self.send(conversation, "撤回后提问")
        messages = json.loads(self.model_requests[-1].content)["messages"]
        self.assertNotIn("先前个性化提问", json.dumps(messages, ensure_ascii=False))
        self.assertNotIn("合成测试病史", json.dumps(messages, ensure_ascii=False))

    async def test_revoked_during_generation_cannot_complete(self):
        self.profile_enabled = True
        self.profile_revision = 1
        self.mode = "revoke-profile"
        conversation = await self.create()
        result = await self.send(conversation)
        parsed = events(result)
        self.assertEqual(parsed[-1][0], "error")
        self.assertEqual(parsed[-1][1]["code"], "PERSONALIZATION_CHANGED")
        history = (await self.history(conversation)).json()["turns"]
        self.assertEqual(history[0]["status"], "failed")

    async def test_profile_change_during_retrieval_stops_before_model(self):
        self.profile_enabled = True
        self.profile_revision = 1
        async def search(query):
            self.profile_revision += 1
            return {"citations": [], "retrieval": {"mode": "empty", "knowledgeRevision": 0}}
        self.app.state.retriever.search = search
        result = await self.send(await self.create())
        self.assertEqual(events(result)[-1][1]["code"], "PERSONALIZATION_CHANGED")
        self.assertEqual(self.model_requests, [])

    async def test_knowledge_change_during_retrieval_stops_before_model(self):
        async def search(query):
            with self.app.state.knowledge.connection(write=True) as conn:
                conn.execute("UPDATE knowledge_meta SET revision=revision+1 WHERE id=1")
            return {"citations": [], "retrieval": {"mode": "empty", "knowledgeRevision": 0}}
        self.app.state.retriever.search = search
        result = await self.send(await self.create())
        self.assertEqual(events(result)[-1][1]["code"], "KNOWLEDGE_CHANGED")
        self.assertEqual(self.model_requests, [])

    async def test_new_knowledge_revision_excludes_old_grounded_history(self):
        conversation = await self.create()
        with self.app.state.knowledge.connection(write=True) as conn:
            conn.execute("UPDATE knowledge_meta SET revision=1 WHERE id=1")
        await self.send(conversation, "旧版知识提问")
        with self.app.state.knowledge.connection(write=True) as conn:
            conn.execute("UPDATE knowledge_meta SET revision=2 WHERE id=1")
        await self.send(conversation, "新版知识提问")
        messages = json.loads(self.model_requests[-1].content)["messages"]
        self.assertNotIn("旧版知识提问", json.dumps(messages, ensure_ascii=False))

    async def test_java_identity_failure_fails_closed_without_details(self):
        for mode, status in (("offline", 503), ("error", 503), ("invalid", 502)):
            self.identity_mode = mode
            response = await self.request("GET", "/ai/v1/conversations")
            self.assertEqual(response.status_code, status)
            self.assertNotIn("sensitive", response.text)

    async def test_service_key_sent_only_to_java_and_no_credentials_in_model_context(self):
        conversation = await self.create()
        response = await self.send(conversation)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(r.headers["X-AI-Service-Key"] == SERVICE_KEY for r in self.java_requests))
        model = self.model_requests[0]
        self.assertNotIn("X-AI-Service-Key", model.headers)
        self.assertNotIn("Authorization", model.headers)
        self.assertNotIn(ALICE, model.content.decode())
        self.assertNotIn(SERVICE_KEY, model.content.decode())
        self.assertEqual(json.loads(model.content)["options"]["temperature"], 0.2)

    async def test_conversation_listing_history_and_post_are_user_scoped(self):
        conversation = await self.create()
        self.assertEqual((await self.history(conversation, BOB)).status_code, 404)
        self.assertEqual((await self.send(conversation, token=BOB)).status_code, 404)
        self.assertEqual((await self.request("GET", "/ai/v1/conversations", BOB)).json(), [])
        self.assertEqual(len((await self.request("GET", "/ai/v1/conversations")).json()), 1)

    async def test_caller_cannot_overpost_user_history_or_model(self):
        response = await self.request(
            "POST", "/ai/v1/conversations", json={"title": "test", "userId": "bob"},
        )
        self.assertEqual(response.status_code, 400)
        conversation = await self.create()
        response = await self.request(
            "POST", f"/ai/v1/conversations/{conversation}/messages",
            json={"requestId": str(uuid.uuid4()), "message": "x", "history": [], "model": "evil"},
        )
        self.assertEqual(response.status_code, 400)

    async def test_stream_completion_persists_and_uses_multiturn_server_history(self):
        conversation = await self.create()
        response = await self.send(conversation, "第一问")
        self.assertEqual([kind for kind, _ in events(response)], ["start", "context", "delta", "delta", "done"])
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        history = (await self.history(conversation)).json()
        self.assertEqual(history["turns"][0]["assistant"], "你好，已收到。")
        self.assertEqual(history["turns"][0]["status"], "completed")
        await self.send(conversation, "第二问")
        context = json.loads(self.model_requests[-1].content)["messages"]
        self.assertEqual([x["role"] for x in context], ["system", "user", "assistant", "user"])
        self.assertEqual(context[1]["content"], "第一问")
        self.assertEqual(context[-1]["content"], "第二问")

    async def test_completed_request_replays_without_new_model_call(self):
        conversation = await self.create()
        request_id = str(uuid.uuid4())
        await self.send(conversation, request_id=request_id)
        response = await self.send(conversation, request_id=request_id)
        self.assertEqual(len(self.model_requests), 1)
        self.assertTrue(events(response)[0][1]["replayed"])
        self.assertTrue(events(response)[-1][1]["replayed"])
        self.assertEqual(len((await self.history(conversation)).json()["turns"]), 1)
        changed = await self.send(conversation, "不同内容", request_id)
        self.assertEqual(changed.status_code, 409)

    async def test_pending_request_and_same_conversation_concurrency_are_rejected(self):
        conversation = await self.create()
        request_id = str(uuid.uuid4())
        self.app.state.store.start("alice", conversation, request_id, "你好", 60)
        self.assertEqual((await self.send(conversation, request_id=request_id)).status_code, 409)
        self.assertEqual((await self.send(conversation)).status_code, 409)
        self.assertEqual(len(self.model_requests), 0)

    async def test_user_active_generation_quota_is_atomic(self):
        ids = [await self.create() for _ in range(3)]
        for conversation in ids[:2]:
            self.app.state.store.start("alice", conversation, str(uuid.uuid4()), "test", 60)
        result = await self.send(ids[2])
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.json()["code"], "TOO_MANY_ACTIVE_TURNS")

    async def test_model_errors_persist_partial_text_and_release_conversation(self):
        conversation = await self.create()
        self.mode = "truncated"
        response = await self.send(conversation)
        self.assertEqual(events(response)[-1][0], "error")
        history = (await self.history(conversation)).json()["turns"]
        self.assertEqual(history[0]["assistant"], "部分回答")
        self.assertEqual(history[0]["status"], "failed")
        self.mode = "normal"
        await self.send(conversation, "新的问题")
        model = json.loads(self.model_requests[-1].content)["messages"]
        self.assertEqual([item["role"] for item in model], ["system", "user"])

    async def test_model_protocol_status_empty_and_transport_errors_are_controlled(self):
        modes = {
            "invalid": "MODEL_PROTOCOL_ERROR", "bad-content": "MODEL_PROTOCOL_ERROR",
            "oversize": "MODEL_PROTOCOL_ERROR", "status": "MODEL_UNAVAILABLE",
            "network": "MODEL_UNAVAILABLE", "read-timeout": "MODEL_TIMEOUT",
            "empty": "MODEL_EMPTY_RESPONSE",
        }
        for mode, code in modes.items():
            with self.subTest(mode=mode):
                self.mode = mode
                response = await self.send(await self.create())
                last = events(response)[-1]
                self.assertEqual(last[0], "error")
                self.assertEqual(last[1]["code"], code)
                self.assertNotIn("sensitive", response.text)
                self.assertNotIn("private", response.text)

    async def test_internal_thinking_is_not_sent_to_client_or_history(self):
        self.mode = "thinking"
        conversation = await self.create()
        response = await self.send(conversation)
        self.assertNotIn("private-reasoning", response.text)
        self.assertEqual((await self.history(conversation)).json()["turns"][0]["assistant"], "公开回答")

    async def test_total_timeout_marks_failed(self):
        self.mode = "slow"
        conversation = await self.create()
        self.app.state.settings = self.settings.model_copy(update={"model_timeout": 0.03})
        response = await self.send(conversation)
        self.assertEqual(events(response)[-1][1]["code"], "MODEL_TIMEOUT")
        self.assertEqual((await self.history(conversation)).json()["turns"][0]["status"], "failed")

    async def test_deadline_survives_disconnect_probe_swallowing_cancellation(self):
        self.mode = "slow"
        self.app.state.settings = self.settings.model_copy(update={"model_timeout": 0.03})
        conversation = await self.create()
        rid = str(uuid.uuid4())
        prepared = self.app.state.store.start("alice", conversation, rid, "超时检查", 60)
        async def probe():
            try:
                await asyncio.sleep(.06)
            except asyncio.CancelledError:
                return False
            return False
        generator = stream_turn(self.app, conversation, rid, "超时检查", "alice", ALICE, prepared, probe)
        frames = [frame async for frame in generator]
        self.assertIn("MODEL_TIMEOUT", frames[-1])

    async def test_output_limit_marks_partial_answer_failed(self):
        conversation = await self.create()
        self.app.state.settings = self.settings.model_copy(update={"output_char_limit": 2})
        response = await self.send(conversation)
        self.assertEqual(events(response)[-1][1]["code"], "MODEL_OUTPUT_LIMIT")
        self.assertEqual((await self.history(conversation)).json()["turns"][0]["assistant"], "你好")

    async def test_cancelled_generator_persists_interruption_and_allows_next_turn(self):
        conversation = await self.create()
        request_id = str(uuid.uuid4())
        store = self.app.state.store
        prepared = store.start("alice", conversation, request_id, "你好", 60)

        async def connected():
            return False

        generator = stream_turn(
            self.app, conversation, request_id, "你好", "alice", ALICE, prepared, connected,
        )
        self.assertIn("event: start", await anext(generator))
        self.assertIn("event: context", await anext(generator))
        self.assertIn("event: delta", await anext(generator))
        await generator.aclose()
        turn = store.history("alice", conversation)["turns"][0]
        self.assertEqual(turn["status"], "interrupted")
        self.assertEqual(turn["assistant"], "你好")
        self.assertEqual((await self.send(conversation)).status_code, 200)

    async def test_disconnected_client_releases_pending_model_task(self):
        conversation = await self.create()
        request_id = str(uuid.uuid4())
        store = self.app.state.store
        prepared = store.start("alice", conversation, request_id, "你好", 60)

        async def disconnected():
            return True

        generator = stream_turn(
            self.app, conversation, request_id, "你好", "alice", ALICE, prepared, disconnected,
        )
        await anext(generator)
        with self.assertRaises(StopAsyncIteration):
            await anext(generator)
        self.assertEqual(store.history("alice", conversation)["turns"][0]["status"], "interrupted")

    async def test_generation_rechecks_revoked_delegation(self):
        conversation = await self.create()
        self.mode = "revoke"
        import itertools
        clock = itertools.count(0, 11)
        with patch("app.main.time", SimpleNamespace(monotonic=lambda: next(clock))):
            response = await self.send(conversation)
        self.assertEqual(events(response)[-1][1]["code"], "UNAUTHORIZED")
        self.assertEqual((await self.history(conversation, BOB)).status_code, 401)

    async def test_expired_lease_recovers_after_worker_interruption(self):
        conversation = await self.create()
        request_id = str(uuid.uuid4())
        store = self.app.state.store
        store.start("alice", conversation, request_id, "旧问题", -1)
        self.assertEqual(store.history("alice", conversation)["turns"][0]["status"], "interrupted")
        self.assertEqual((await self.send(conversation, "新问题")).status_code, 200)
        self.assertEqual(store.history("alice", conversation)["turns"][0]["errorCode"], "SERVER_INTERRUPTED")
        self.assertEqual((await self.send(conversation, "旧问题", request_id)).status_code, 409)

    async def test_context_budget_preserves_complete_turn_pairs_and_current_message(self):
        conversation = await self.create()
        store = self.app.state.store
        for text in ("one", "two", "three"):
            rid = str(uuid.uuid4())
            store.start("alice", conversation, rid, text, 60)
            store.finish(conversation, rid, text + "-answer", "completed")
        context = store.context("alice", conversation, "now", 2, 4500)
        self.assertEqual([x["content"] for x in context], ["two", "two-answer", "three", "three-answer", "now"])
        context = store.context("alice", conversation, "now", 10, 5)
        self.assertEqual(context, [{"role": "user", "content": "now"}])

    async def test_conversation_history_survives_store_restart(self):
        conversation = await self.create()
        await self.send(conversation)
        from app.store import ConversationStore
        restarted = ConversationStore(self.settings.database_path)
        self.assertEqual(restarted.history("alice", conversation)["turns"][0]["status"], "completed")
        with self.assertRaises(AppError):
            restarted.history("bob", conversation)

    async def test_invalid_body_uuid_and_payload_size_are_rejected(self):
        conversation = await self.create()
        self.assertEqual((await self.history("not-a-uuid")).status_code, 400)
        for text in ("", "   ", "x" * 4001):
            self.assertEqual((await self.send(conversation, text)).status_code, 400)
        response = await self.request(
            "POST", "/ai/v1/conversations", json={"title": "x" * 40000},
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(len(self.model_requests), 0)

    async def test_failed_request_cannot_be_replayed_as_completed(self):
        self.mode = "truncated"
        conversation = await self.create()
        rid = str(uuid.uuid4())
        await self.send(conversation, request_id=rid)
        response = await self.send(conversation, request_id=rid)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "TURN_NOT_REPLAYABLE")

    async def test_openapi_declares_sse_and_bearer_security(self):
        spec = self.app.openapi()
        self.assertIn("HTTPBearer", spec["components"]["securitySchemes"])
        route = spec["paths"]["/ai/v1/conversations/{conversation_id}/messages"]["post"]
        self.assertIn("text/event-stream", route["responses"]["200"]["content"])
        self.assertEqual(route["security"], [{"HTTPBearer": []}])
        self.assertNotIn("422", route["responses"])
        self.assertIn("400", route["responses"])

    async def test_first_model_delta_is_available_before_model_stream_finishes(self):
        from app.model import OllamaModel
        gate = asyncio.Event()

        class GatedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                first = frames("首段", done=False)
                for byte in first:
                    yield bytes([byte])
                await gate.wait()
                yield frames("后段")

        async def handler(request):
            return httpx.Response(200, stream=GatedBody())

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            iterator = OllamaModel(client, self.settings).stream([{"role": "user", "content": "test"}])
            first = await asyncio.wait_for(anext(iterator), 0.5)
            self.assertEqual(first, "首段")
            self.assertFalse(gate.is_set())
            gate.set()
            self.assertEqual(await anext(iterator), "后段")
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)

    async def test_cancellation_while_model_is_pending_releases_turn(self):
        conversation = await self.create()
        self.mode = "slow"
        request_id = str(uuid.uuid4())
        store = self.app.state.store
        prepared = store.start("alice", conversation, request_id, "你好", 60)

        async def connected():
            return False

        generator = stream_turn(
            self.app, conversation, request_id, "你好", "alice", ALICE, prepared, connected,
        )
        await anext(generator)
        await anext(generator)
        pending = asyncio.create_task(anext(generator))
        await asyncio.sleep(0.02)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(store.history("alice", conversation)["turns"][0]["status"], "interrupted")
        self.assertFalse(any(task.get_coro().__qualname__.endswith("OllamaModel.stream")
                             for task in asyncio.all_tasks() if not task.done()))

    def test_settings_reject_missing_key_and_unsafe_service_url(self):
        from pydantic import ValidationError
        for values in ({"service_key": ""}, {"service_key": SERVICE_KEY, "java_base_url": "file:///tmp"},
                       {"service_key": SERVICE_KEY, "java_base_url": "http://user:pass@host"},
                       {"service_key": SERVICE_KEY, "model_temperature": 1.1},
                       {"service_key": SERVICE_KEY, "model_temperature": -0.1}):
            with self.assertRaises(ValidationError):
                Settings(**values)


if __name__ == "__main__":
    unittest.main()
