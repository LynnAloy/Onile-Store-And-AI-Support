export async function consumeOrderGrant({ issue, isCurrent, discard, use }) {
  const grant = await issue();
  if (!isCurrent()) {
    await discard(grant);
    return;
  }
  return use(grant);
}

export async function issueOwnerBoundOrderGrant(data, ownerToken, { baseURL = "", fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${baseURL}/api/auth/order-agent-token`, {
    method: "POST", headers: { Authorization: `Bearer ${ownerToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(data), cache: "no-store", signal: AbortSignal.timeout(15000),
  });
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.message || "订单准备授权失败"), { code: result.code });
  return result;
}
