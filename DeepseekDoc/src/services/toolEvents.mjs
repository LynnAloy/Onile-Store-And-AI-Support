const tools = new Set(["list_inventory", "analyze_inventory", "search_medicines", "get_medicine", "get_my_order", "prepare_order_draft", "propose_purchase"]);
const identifier = /^[A-Za-z0-9_-]{1,64}$/;
const amount = /^(0|[1-9]\d{0,9})\.\d{2}$/;
const positive = (value) => Number.isSafeInteger(value) && value > 0;
const text = (value, limit) => typeof value === "string" && value.length > 0 && value.length <= limit;

export function validToolEvent(kind, data) {
  if (!["tool_started", "tool_result"].includes(kind) || !data || typeof data !== "object"
    || !tools.has(data.tool) || !text(data.callId, 64) || !identifier.test(data.callId)) return false;
  if (kind === "tool_started") return data.status === "running";
  if (!["completed", "failed"].includes(data.status) || !Number.isSafeInteger(data.durationMs)
    || data.durationMs < 0 || data.durationMs > 300000) return false;
  const result = data.result;
  if (!result || typeof result.ok !== "boolean") return false;
  if (!result.ok) return data.status === "failed" && text(result.code, 64);
  if (data.status !== "completed") return false;
  if (data.tool === "analyze_inventory") {
    const items = result.analysis?.items;
    return Array.isArray(items) && items.length <= 20 && items.every(item =>
      item && positive(item.medicineId) && text(item.name, 200) && amount.test(item.price)
      && item.currency === "CNY" && Number.isSafeInteger(item.stock) && item.stock >= 0
      && (typeof item.matchesNeed === "boolean"
        || (item.matchesNeed === null && item.status === "insufficient_evidence")));
  }
  if (data.tool === "propose_purchase") {
    const proposal = result.proposal;
    return proposal?.requiresUserAuthorization === true && proposal.snapshot === true
      && Array.isArray(proposal.items) && proposal.items.length > 0 && proposal.items.length <= 10
      && new Set(proposal.items.map(item => item.id)).size === proposal.items.length
      && proposal.items.every(item => positive(item.id) && text(item.name, 200) && amount.test(item.price)
        && Number.isSafeInteger(item.stock) && item.stock >= 0 && item.currency === "CNY"
        && (item.quantity === null || (positive(item.quantity) && item.quantity <= 99))
        && ["explicit", "missing"].includes(item.quantitySource) && typeof item.autoSelect === "boolean"
        && typeof item.draftEligible === "boolean" && typeof item.draftBlockedReason === "string");
  }
  if (data.tool === "prepare_order_draft") {
    const draft = result.draft;
    return draft && text(draft.draftId, 64) && identifier.test(draft.draftId)
      && ["PREPARED", "CONFIRMED", "CANCELLED", "EXPIRED"].includes(draft.status)
      && positive(draft.version) && draft.paid === false && draft.currency === "CNY"
      && amount.test(draft.totalPrice) && Number.isSafeInteger(draft.expiresAt)
      && Array.isArray(draft.items) && draft.items.length > 0 && draft.items.length <= 10
      && draft.items.every((item) => positive(item.medicineId) && positive(item.quantity)
        && item.quantity <= 99 && text(item.name, 200) && amount.test(item.price));
  }
  if (data.tool !== "get_my_order") {
    const limit = data.tool === "list_inventory" ? 20 : data.tool === "search_medicines" && result.catalogListing === true ? 100 : 10;
    return Array.isArray(result.products) && result.products.length <= limit
      && result.products.every((p) => p && positive(p.id) && text(p.name, 200)
        && amount.test(p.price) && Number.isSafeInteger(p.stock) && p.stock >= 0 && p.currency === "CNY");
  }
  const order = result.order;
  return order && text(order.orderId, 64) && identifier.test(order.orderId)
    && text(order.status, 40) && amount.test(order.totalPrice) && order.currency === "CNY"
    && Array.isArray(order.items) && order.items.length <= 50
    && order.items.every((item) => positive(item.medicineId) && positive(item.quantity)
      && text(item.name, 200) && amount.test(item.price));
}

export function toolRows(events = []) {
  const rows = new Map();
  for (const entry of events) {
    if (!validToolEvent(entry.kind, entry.data)) throw new Error("工具事件格式异常");
    rows.set(entry.data.callId, entry.data);
  }
  return [...rows.values()];
}

export const toolLabel = (name) => ({
  list_inventory: "读取实时库存",
  analyze_inventory: "逐项分析库存",
  propose_purchase: "待核对清单",
  prepare_order_draft: "未付款草稿",
  search_medicines: "查询商品", get_medicine: "查询商品详情", get_my_order: "查询本人订单",
}[name] || "工具查询");

