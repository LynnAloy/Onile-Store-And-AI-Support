import test from "node:test";
import assert from "node:assert/strict";
import { consumeSSE, createAIClient } from "../src/services/aiClient.mjs";

const encoder = new TextEncoder();
const grant = (token = "a".repeat(43)) => ({
  token, scope: "AGENT_READ", expiresAt: Math.floor(Date.now() / 1000) + 300,
});
const frame = (kind, value) => `event: ${kind}\ndata: ${JSON.stringify(value)}\n\n`;
const finish = () => frame("done", { status: "completed" });

function stream(text, split = 1) {
  const bytes = encoder.encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += split) controller.enqueue(bytes.slice(i, i + split));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

test("SSE handles UTF-8 byte boundaries, multiline text and CRLF", async () => {
  const text = (frame("delta", { text: "你好\n第二行" }) + finish()).replace(/\n/g, "\r\n");
  const received = [];
  await consumeSSE(stream(text), (kind, data) => received.push([kind, data]));
  assert.equal(received[0][1].text, "你好\n第二行");
  assert.equal(received[1][0], "done");
});

test("heartbeat is ignored and explicit done terminates the stream", async () => {
  const received = [];
  await consumeSSE(stream(": ping\n\n" + finish()), (kind) => received.push(kind));
  assert.deepEqual(received, ["done"]);
});

test("truncated stream is not mistaken for completion", async () => {
  await assert.rejects(
    consumeSSE(stream(frame("delta", { text: "partial" })), () => {}),
    (error) => error.code === "STREAM_INTERRUPTED",
  );
});

test("SSE error retains a safe error code", async () => {
  await assert.rejects(
    consumeSSE(stream(frame("error", { code: "MODEL_TIMEOUT", message: "超时" })), () => {}),
    (error) => error.code === "MODEL_TIMEOUT" && error.message === "超时",
  );
});

test("malformed JSON and invalid event shapes are rejected", async () => {
  for (const body of [
    "event: delta\ndata: not-json\n\n",
    frame("delta", { text: 5 }),
    frame("done", { status: "failed" }),
    frame("delta", null),
  ]) {
    await assert.rejects(consumeSSE(stream(body), () => {}),
      (error) => error.code === "STREAM_PROTOCOL_ERROR");
  }
});

test("unexpected content type and oversized event are rejected", async () => {
  await assert.rejects(consumeSSE(new Response("<html>proxy error</html>"), () => {}));
  await assert.rejects(consumeSSE(stream("data: " + "x".repeat(65537), 8192), () => {}));
});

test("abort closes a pending stream reader", async () => {
  let cancelled = false;
  const controller = new AbortController();
  const response = new Response(new ReadableStream({
    cancel() { cancelled = true; },
  }), { headers: { "Content-Type": "text/event-stream" } });
  const promise = consumeSSE(response, () => {}, controller.signal);
  controller.abort();
  await assert.rejects(promise, (error) => error.name === "AbortError");
  assert.equal(cancelled, true);
});

test("AI transport carries delegation and never a Java USER token", async () => {
  let issued = 0;
  const requests = [];
  const client = createAIClient({
    getDelegation: async () => { issued++; return grant(); },
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return Response.json([]);
    },
  });
  await client.list();
  await client.list();
  assert.equal(issued, 1);
  assert.equal(requests[0].options.headers.Authorization, "Bearer " + grant().token);
  assert.equal(requests[0].options.headers["X-AI-Service-Key"], undefined);
  assert.equal(requests[0].url, "/ai/v1/conversations");
});

test("concurrent requests share one delegation exchange", async () => {
  let issued = 0;
  const client = createAIClient({
    getDelegation: async () => { issued++; await Promise.resolve(); return grant(); },
    fetchImpl: async () => Response.json([]),
  });
  await Promise.all([client.list(), client.list()]);
  assert.equal(issued, 1);
});

test("expired delegation is renewed", async () => {
  let issued = 0;
  const client = createAIClient({
    getDelegation: async () => { issued++; return grant(); },
    fetchImpl: async () => Response.json([]),
  });
  await client.list();
  client.resetAuthorization();
  await client.list();
  assert.equal(issued, 2);
});

test("401 refresh is bounded to one retry", async () => {
  let fetched = 0;
  let issued = 0;
  const client = createAIClient({
    getDelegation: async () => { issued++; return grant(); },
    fetchImpl: async () => {
      fetched++;
      return Response.json({ code: "UNAUTHORIZED", message: "授权失效" }, { status: 401 });
    },
  });
  await assert.rejects(client.list(), (error) => error.code === "UNAUTHORIZED");
  assert.equal(fetched, 2);
  assert.equal(issued, 2);
});

test("authorization returned after a user switch is discarded", async () => {
  let release;
  const client = createAIClient({
    getDelegation: () => new Promise((resolve) => { release = resolve; }),
    fetchImpl: async () => { throw new Error("Must not send stale authorization"); },
  });
  const pending = client.list();
  client.resetAuthorization();
  release(grant());
  await assert.rejects(pending, (error) => error.name === "AbortError");
});

test("request cancellation prevents a transport call", async () => {
  const controller = new AbortController();
  controller.abort();
  const client = createAIClient({
    getDelegation: async () => grant(),
    fetchImpl: async () => { throw new Error("Must not call fetch"); },
  });
  await assert.rejects(client.list(controller.signal), (error) => error.name === "AbortError");
});

test("chat is POST JSON and stream errors do not auto-resubmit a turn", async () => {
  let fetched = 0;
  const client = createAIClient({
    getDelegation: async () => grant(),
    fetchImpl: async (url, options) => {
      fetched++;
      assert.equal(options.method, "POST");
      assert.deepEqual(JSON.parse(options.body), { message: "你好", requestId: "request-id" });
      return stream(frame("error", { code: "MODEL_UNAVAILABLE", message: "模型不可用" }));
    },
  });
  await assert.rejects(client.stream("conversation", "你好", "request-id", () => {}),
    (error) => error.code === "MODEL_UNAVAILABLE");
  assert.equal(fetched, 1);
});

test("only AGENT_READ delegation is accepted", async () => {
  const client = createAIClient({
    getDelegation: async () => ({ ...grant(), scope: "USER" }),
    fetchImpl: async () => { throw new Error("Must not send full USER credential"); },
  });
  await assert.rejects(client.list(), (error) => error.code === "UNAUTHORIZED");
});
