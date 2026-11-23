export const commerceEnabled = import.meta.env?.VITE_COMMERCE_ENABLED === "true";

export function createCommerceClient({ fetchImpl = fetch, baseURL = "", timeout = 35000 } = {}) {
  async function request(method, path, owner, body) {
    if (!owner?.token) throw new Error("请先登录");
    let response;
    try {
      response = await fetchImpl(baseURL + path, {
        method, headers: { Authorization: `Bearer ${owner.token}`, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: "no-store", redirect: "error", signal: AbortSignal.timeout(timeout),
      });
    } catch {
      throw Object.assign(new Error("请求结果未确认，请查询原下单记录，勿重复发送购买消息"), { outcome: "UNKNOWN" });
    }
    let data;
    try { data = await response.json(); } catch {
      throw Object.assign(new Error("服务结果未确认，请查询原下单记录"), { outcome: "UNKNOWN" });
    }
    if (!response.ok) throw Object.assign(new Error(data.message || "操作未完成"), {
      code: data.code, outcome: data.outcome || (method === "POST" && path.endsWith("/execute") && response.status >= 500 ? "UNKNOWN" : "NOT_APPLIED"), status: response.status,
    });
    return data;
  }
  const turnPath = id => `/api/auto-orders/turns/${encodeURIComponent(id)}`;
  return {
    modelConfig: owner => request("GET", "/api/admin/ai-config", owner),
    saveModelConfig: (body, owner) => request("PUT", "/api/admin/ai-config", owner, body),
    permissions: owner => request("GET", "/api/account/permissions", owner),
    medicines: owner => request("GET", "/api/admin/medicines", owner),
    evidence: (id, owner) => request("GET", `/api/admin/medicines/${encodeURIComponent(id)}/evidence`, owner),
    saveEvidence: (id, body, owner) => request("PUT", `/api/admin/medicines/${encodeURIComponent(id)}/evidence`, owner, body),
    audit: (id, owner) => request("GET", `/api/admin/medicines/${id}/audit`, owner),
    review: (id, body, owner) => request("PUT", `/api/admin/medicines/${id}/qualification`, owner, body),
    stock: (id, body, owner) => request("PUT", `/api/admin/medicines/${id}/stock`, owner, body),
    policy: owner => request("GET", "/api/wallet/auto-order-policy", owner),
    updatePolicy: (body, owner) => request("PUT", "/api/wallet/auto-order-policy", owner, body),
    register: (body, owner) => request("POST", "/api/auto-orders/turns", owner, body),
    execute: (id, items, owner) => request("POST", turnPath(id) + "/execute", owner, { items }),
    read: (id, owner) => request("GET", turnPath(id), owner),
    history: (conversationId, owner) => request("GET", "/api/auto-orders/turns?conversationId=" + encodeURIComponent(conversationId), owner),
  };
}

// Only live, completed turns may spend. Replaying chat history never invokes this function.
export async function fulfillAutoProposal({ proposal, turn, owner, isCurrent, client, onAttempt = () => {} }) {
  if (!isCurrent() || turn?.status !== "READY") return undefined;
  if (proposal?.riskAssessment?.automaticPurchaseAllowed === false) {
    return { status: "MANUAL", message: "健康资料风险未排除或信息不足，本轮不自动扣款，请人工核对。" };
  }
  if (!proposal?.items?.length || proposal.items.some(item => item.autoSelect !== true
    || item.draftEligible !== true || !Number.isInteger(item.quantity)
    || item.quantity < 1 || item.quantity > 99 || item.quantity > item.stock)) {
    return { status: "MANUAL", message: "清单中有商品、规格或数量需要核对，本次未自动下单。" };
  }
  const items = proposal.items.map(item => ({ medicineId: item.id, quantity: item.quantity }));
  onAttempt(turn.turnId, owner);
  // One write only. Network/commit ambiguity is resolved through the same turn's read endpoint.
  try {
    const result = await client.execute(turn.turnId, items, owner);
    if (!['PAID', 'REJECTED'].includes(result?.status)) throw Object.assign(new Error('下单结果不是明确终态'), { outcome: 'UNKNOWN' });
    return result;
  } catch (error) {
    if (error.outcome !== "UNKNOWN") throw error;
    let result;
    try { result = await client.read(turn.turnId, owner); }
    catch (queryError) {
      throw Object.assign(new Error("原扣款结果仍未确认，请恢复登录后查询原轮次，勿重复购买"), {
        outcome: "UNKNOWN", turnId: turn.turnId, code: queryError.code, status: queryError.status,
      });
    }
    if (result.status === "PAID" || result.status === "REJECTED") return result;
    return { status: "UNKNOWN", turnId: turn.turnId, message: "未确认扣款结果，请查询本轮记录及付款订单，勿重复发送购买消息。" };
  }
}
