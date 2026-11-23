import test from "node:test";
import assert from "node:assert/strict";
import { validToolEvent } from "../src/services/toolEvents.mjs";
import { createAIClient } from "../src/services/aiClient.mjs";

const grant = { token: "a".repeat(43), scope: "AGENT_READ", expiresAt: Math.floor(Date.now() / 1000) + 300 };
const draft = { draftId: "draft-1", status: "PREPARED", version: 1, totalPrice: "0.74", paid: false,
  currency: "CNY", expiresAt: 2000000000, items: [{ medicineId: 1, quantity: 2, name: "合成商品", price: "0.37" }] };
const result = { callId: "call-1", tool: "prepare_order_draft", status: "completed", durationMs: 20, result: { ok: true, draft } };

test("draft events require an unpaid bounded server snapshot", () => {
  assert.equal(validToolEvent("tool_result", result), true);
  const changed = structuredClone(result);
  changed.result.draft.paid = true;
  assert.equal(validToolEvent("tool_result", changed), false);
  changed.result.draft.paid = false;
  changed.result.draft.items[0].quantity = 100;
  assert.equal(validToolEvent("tool_result", changed), false);
});

test("draft transport sends a separate header and only structured items in JSON", async () => {
  let observed;
  const client = createAIClient({
    getDelegation: async () => grant,
    fetchImpl: async (url, options) => {
      observed = options;
      return new Response("event: done\ndata: {\"status\":\"completed\"}\n\n",
        { headers: { "content-type": "text/event-stream" } });
    },
  });
  await client.stream("conversation", "明确授权准备", "rid", () => {}, undefined,
    { token: "o".repeat(43), items: [{ medicineId: 1, quantity: 2 }], recipientPhone: "must-not-send" });
  assert.equal(observed.headers.Authorization, "Bearer " + grant.token);
  assert.equal(observed.headers["X-Order-Agent-Token"], "o".repeat(43));
  const payload = JSON.parse(observed.body);
  assert.deepEqual(payload.purchaseIntent.items, [{ medicineId: 1, quantity: 2 }]);
  assert.equal(observed.body.includes("must-not-send"), false);
  assert.equal(observed.body.includes("o".repeat(43)), false);
});

test("expired order preparation grant does not trigger automatic reauthorization and resubmission", async () => {
  let calls = 0;
  const client = createAIClient({
    getDelegation: async () => grant,
    fetchImpl: async () => {
      calls++;
      return new Response(JSON.stringify({ code: "ORDER_AUTHORIZATION_INVALID", message: "授权失效" }),
        { status: 401, headers: { "content-type": "application/json" } });
    },
  });
  await assert.rejects(client.stream("cid", "准备", "rid", () => {}, undefined,
    { token: "o".repeat(43), items: [{ medicineId: 1, quantity: 2 }] }),
    (error) => error.code === "ORDER_AUTHORIZATION_INVALID");
  assert.equal(calls, 1);
});

