import test from "node:test";
import assert from "node:assert/strict";
import { validToolEvent, toolRows } from "../src/services/toolEvents.mjs";
import { consumeSSE } from "../src/services/aiClient.mjs";

const start = { callId: "call-1", tool: "search_medicines", status: "running" };
const result = {
  ...start, status: "completed", durationMs: 30,
  result: { ok: true, products: [{ id: 1, name: "<script>data</script>", price: "0.10", stock: 0, currency: "CNY" }] },
};

test("tool events validate snapshots including zero stock and exact money strings", () => {
  assert.equal(validToolEvent("tool_started", start), true);
  assert.equal(validToolEvent("tool_result", result), true);
  assert.equal(validToolEvent("tool_result", { ...result, tool: "pay_order" }), false);
  const invalid = structuredClone(result);
  invalid.result.products[0].price = "NaN";
  assert.equal(validToolEvent("tool_result", invalid), false);
});

test("tool rows replace running state and restore history without executing anything", () => {
  const rows = toolRows([{ kind: "tool_started", data: start }, { kind: "tool_result", data: result }]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].status, "completed");
  assert.equal(rows[0].result.products[0].name, "<script>data</script>");
});

test("SSE preserves tool sequence and rejects malformed tool results", async () => {
  const frame = (kind, data) => "event: " + kind + "\ndata: " + JSON.stringify(data) + "\n\n";
  const response = (data) => new Response(data, { headers: { "content-type": "text/event-stream" } });
  const kinds = [];
  await consumeSSE(response(frame("tool_started", start) + frame("tool_result", result)
    + frame("done", { status: "completed" })), (kind) => kinds.push(kind));
  assert.deepEqual(kinds, ["tool_started", "tool_result", "done"]);
  await assert.rejects(consumeSSE(response(frame("tool_result", { tool: "pay_order" })), () => {}),
    (error) => error.code === "STREAM_PROTOCOL_ERROR");
});

