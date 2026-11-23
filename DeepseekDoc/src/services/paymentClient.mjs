export const paymentsEnabled = import.meta.env?.VITE_PAYMENTS_ENABLED === "true";

export function createPaymentClient({ baseURL = "", fetchImpl = fetch, timeout = 15000 } = {}) {
  async function request(method, path, owner, body, headers = {}) {
    if (!owner?.token) throw Object.assign(new Error("请重新登录"), { code: "UNAUTHORIZED", outcome: "NOT_APPLIED" });
    let result;
    try {
      result = await fetchImpl(baseURL + path, {
        method, headers: { Authorization: `Bearer ${owner.token}`, "Content-Type": "application/json", ...headers },
        body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", redirect: "error",
        keepalive: method === "DELETE",
        signal: AbortSignal.timeout(timeout),
      });
    } catch {
      throw Object.assign(new Error("网络连接未完成，请查询原订单核实结果"), { code: "NETWORK_ERROR", outcome: "UNKNOWN" });
    }
    let data;
    try { data = await result.json(); } catch {
      throw Object.assign(new Error("服务响应无法确认，请查询原订单"), { code: "INVALID_RESPONSE", outcome: "UNKNOWN", status: result.status });
    }
    if (!result.ok) throw Object.assign(new Error(data.message || "请求未完成"), {
      code: data.code, outcome: data.outcome, status: result.status, retryAfter: Number(result.headers.get("Retry-After")) || 0,
    });
    return data;
  }
  const orderPath = id => `/api/orders/${encodeURIComponent(id)}`;
  return {
    checkout: (id, version, key, owner) => request("POST", `/api/order-drafts/${encodeURIComponent(id)}/checkout`, owner,
      { expectedVersion: version }, { "Idempotency-Key": key }),
    read: (id, owner, key) => request("GET", orderPath(id) + (key ? `?paymentRequestKey=${encodeURIComponent(key)}` : ""), owner),
    list: (owner, phone) => request("GET", "/api/orders" + (phone ? `?phone=${encodeURIComponent(phone)}` : ""), owner),
    wallet: owner => request("GET", `/api/wallet/${encodeURIComponent(owner.userId)}`, owner),
    authorize: (id, version, password, owner) => request("POST", orderPath(id) + "/payment-authorizations", owner,
      { expectedVersion: version, password }),
    revoke: async (id, authorizationId, owner) => {
      if (!authorizationId) throw new Error("撤销授权必须指定授权编号");
      try {
        return await request("DELETE", orderPath(id) + `/payment-authorizations?authorizationId=${encodeURIComponent(authorizationId)}`, owner);
      } catch (error) {
        if (error.status !== 401 || error.code !== "UNAUTHORIZED") throw error;
        // An invalid parent session cannot spend its grant. Never expire a different account here.
      }
    },
    pay: (id, version, key, token, owner) => request("POST", orderPath(id) + "/pay", owner,
      { expectedVersion: version }, { "Idempotency-Key": key, "X-Payment-Authorization": token }),
    close: (id, version, owner) => request("POST", orderPath(id) + "/close", owner, { expectedVersion: version }),
  };
}

export const paymentStatusLabel = status => ({
  PENDING_PAYMENT: "待付款", PAID: "已付款", CLOSED: "已关闭", LEGACY_UNVERIFIED: "历史订单（未接入新支付验证）",
}[status] || "历史业务订单");

export const paymentErrorMessage = error => ({
  PAYMENT_ATTEMPT_EXPIRED: "上次付款请求已核实未执行并结束。请重新验证后，再明确付款。",
  PAYMENT_VERIFICATION_FAILED: "支付密码验证失败，请检查后重试。连续五次失败将锁定15分钟。",
  RATE_LIMITED: "验证已锁定，请等待15分钟后再试。",
  PAYMENT_AUTHORIZATION_INVALID: "支付授权已失效，请重新核对并独立验证。",
  OUT_OF_STOCK: "库存不足，本次未付款。补货后请重新验证。",
  INSUFFICIENT_BALANCE: "演示钱包余额不足，本次未付款。充值后请重新验证。",
  PRICE_CHANGED: "商品已调价，订单已关闭，请重新准备并核对草稿。",
  SALE_NOT_ALLOWED: "商品销售资格已变化，请回到对话重新核对。",
  QUALIFICATION_CHANGED: "商品审核版本已变化，请重新准备草稿。",
  ORDER_VERSION_CONFLICT: "订单版本已变化，请刷新并重新核对。",
  ORDER_EXPIRED: "订单已到期，请重新准备草稿。",
  ORDER_CLOSED: "订单已关闭，不能继续付款。",
  PAYMENTS_DISABLED: "本环境尚未启用独立付款，请使用隔离演示环境。",
  POINTS_LIMIT: "账户积分已达上限，本次未付款，请联系管理人员核对。",
  UNAUTHORIZED: "登录会话已失效，请重新登录后查询原订单。",
}[error?.code] || error?.message || "请求未完成，请查询原订单核实结果");
