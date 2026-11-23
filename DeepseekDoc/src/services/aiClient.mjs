import { validToolEvent } from "./toolEvents.mjs";

export class AIError extends Error {
  constructor(message, code = "AI_ERROR") {
    super(message);
    this.code = code;
  }
}

export async function consumeSSE(response, onEvent, signal) {
  if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body) {
    throw new AIError("AI服务返回了无效的数据格式", "STREAM_PROTOCOL_ERROR");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  const cancel = () => { reader.cancel().catch(() => {}); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("已取消", "AbortError");
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.length > 65536) throw new AIError("数据帧过长", "STREAM_PROTOCOL_ERROR");
        let kind = "message";
        const data = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) kind = line.slice(6).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        }
        if (!data.length) continue;
        let payload;
        try {
          payload = JSON.parse(data.join("\n"));
        } catch {
          throw new AIError("AI数据解析失败", "STREAM_PROTOCOL_ERROR");
        }
        if (!payload || typeof payload !== "object"
          || (kind === "delta" && typeof payload.text !== "string")
          || (kind === "done" && payload.status !== "completed")
          || (["tool_started", "tool_result"].includes(kind) && !validToolEvent(kind, payload))) {
          throw new AIError("AI事件格式异常", "STREAM_PROTOCOL_ERROR");
        }
        if (kind === "error") throw new AIError(payload.message || "回答失败", payload.code);
        if (kind === "done") completed = true;
        onEvent(kind, payload);
      }
      if (buffer.length > 65536) throw new AIError("数据帧过长", "STREAM_PROTOCOL_ERROR");
      if (done || completed) break;
    }
    if (signal?.aborted) throw new DOMException("已取消", "AbortError");
    if (!completed) throw new AIError("连接提前结束，回答未完成", "STREAM_INTERRUPTED");
  } finally {
    signal?.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function createAIClient({ getDelegation, fetchImpl = fetch, baseURL = "" }) {
  let grant;
  let pendingGrant;
  let epoch = 0;

  function resetAuthorization() {
    epoch++;
    grant = undefined;
    pendingGrant = undefined;
  }

  async function credentials() {
    if (grant && grant.expiresAt * 1000 > Date.now() + 15000) return grant.token;
    if (!pendingGrant) {
      const version = epoch;
      const promise = getDelegation().then((value) => {
        if (epoch !== version) throw new DOMException("会话已切换", "AbortError");
        if (!value.token || value.scope !== "AGENT_READ" || value.expiresAt * 1000 <= Date.now()) {
          throw new AIError("AI授权无效，请重新登录", "UNAUTHORIZED");
        }
        grant = value;
        return value.token;
      }).finally(() => {
        if (pendingGrant === promise) pendingGrant = undefined;
      });
      pendingGrant = promise;
    }
    return pendingGrant;
  }

  async function request(path, options = {}) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const token = await credentials();
      if (options.signal?.aborted) throw new DOMException("已取消", "AbortError");
      const duration = options.method === "POST" && path.endsWith("/messages") ? 250000 : 15000;
      const timeout = AbortSignal.timeout(duration);
      const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
      const response = await fetchImpl(baseURL + path, {
        ...options,
        signal,
        headers: { ...options.headers, "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      });
      if (response.status === 401 && attempt === 0 && !options.headers?.["X-Order-Agent-Token"]) {
        resetAuthorization();
        continue;
      }
      if (!response.ok) {
        let body = {};
        try { body = await response.json(); } catch {}
        throw new AIError(body.message || "AI服务请求失败", body.code || "AI_UNAVAILABLE");
      }
      return response;
    }
  }

  const api = {
    resetAuthorization,
    list: async (signal) => (await request("/ai/v1/conversations", { signal })).json(),
    create: async (signal) => (await request("/ai/v1/conversations", {
      method: "POST", signal, body: JSON.stringify({ title: "新对话" }),
    })).json(),
    history: async (id, signal) => (await request(
      `/ai/v1/conversations/${encodeURIComponent(id)}/messages`, { signal },
    )).json(),
    stream: async (id, message, requestId, onEvent, signal, orderPreparation) => {
      const response = await request(`/ai/v1/conversations/${encodeURIComponent(id)}/messages`, {
        method: "POST", signal,
        headers: orderPreparation ? { "X-Order-Agent-Token": orderPreparation.token } : {},
        body: JSON.stringify({ message, requestId,
          ...(orderPreparation ? { purchaseIntent: { items: orderPreparation.items } } : {}) }),
      });
      await consumeSSE(response, onEvent, signal);
    },
  };
  return api;
}
