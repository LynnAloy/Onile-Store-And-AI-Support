import { paymentErrorMessage } from "./paymentClient.mjs";

export function createPaymentFlow({ api, getOwner, recovery, onChange, onSessionExpired = () => {},
  now = () => Math.floor(Date.now() / 1000), makeKey = () => crypto.randomUUID() }) {
  let epoch = 0;
  let authEpoch = 0;
  let context;
  let grant;
  let inFlightGrant;
  let attempt;
  let state = {};
  const publish = patch => { state = { ...state, ...patch }; onChange({ ...state }); };
  const isCurrent = ctx => ctx && ctx === context && ctx.epoch === epoch
    && ctx.owner.userId === getOwner()?.userId && ctx.owner.token === getOwner()?.token;
  const expired = order => order.expiresAt <= now();
  const uncertain = () => publish({ phase: "uncertain", busy: false, hasAuthorization: false,
    message: "正在核实付款结果。请查询原订单，不要重新下单或再次付款。" });

  async function discard(value, ctx) {
    if (!value || !ctx) return;
    try { await api.revoke(ctx.id, value.authorizationId, ctx.owner); } catch {
      if (isCurrent(ctx)) publish({ cleanupWarning: "授权撤销未确认。请勿使用旧授权，最长60秒后失效。" });
    }
  }
  function clearGrant(ctx = context) {
    const prior = grant;
    grant = null;
    publish({ hasAuthorization: false, authorizationExpiresAt: 0 });
    void discard(prior, ctx);
  }
  function failure(error, ctx) {
    if (!isCurrent(ctx)) return;
    publish({ message: paymentErrorMessage(error), code: error.code, busy: false,
      verificationLockedUntil: error.code === "RATE_LIMITED" ? now() + (error.retryAfter || 900) : state.verificationLockedUntil });
    if (error.code === "UNAUTHORIZED") onSessionExpired(ctx.owner);
  }
  function acceptOrder(order, ctx) {
    publish({ order, receipt: order.payment || null, busy: false });
    if (order.paymentStatus === "PAID" || order.paymentStatus === "CLOSED") {
      try { recovery.clear(ctx.owner.userId, ctx.id); } catch {}
      attempt = null;
      publish({ phase: order.paymentStatus === "PAID" ? "paid" : "closed", message: "" });
    } else if (order.paymentStatus !== "PENDING_PAYMENT") publish({ phase: "legacy", message: "历史订单未接入新支付验证，不能在此付款。" });
    else if (attempt && !attempt.retryable && order.requestOutcome?.status !== "REJECTED") uncertain();
    else {
      const code = order.requestOutcome?.code;
      if (order.requestOutcome?.status === "REJECTED") {
        try { recovery.clear(ctx.owner.userId, ctx.id); } catch {}
        attempt = null;
      }
      publish({ phase: "ready", message: code ? paymentErrorMessage({ code })
        : attempt?.retryable ? "上次请求已确认未执行。重新验证后，可使用原请求键明确重试。" : "", code });
    }
  }
  async function load(id) {
    const old = context;
    clearGrant(old);
    void discard(inFlightGrant, old);
    inFlightGrant = null;
    epoch++;
    authEpoch++;
    const owner = getOwner();
    context = { id, owner: { ...owner }, epoch };
    const ctx = context;
    attempt = null;
    publish({ order: null, receipt: null, phase: "loading", busy: true, message: "", code: "", cleanupWarning: "",
      verificationLockedUntil: old?.owner.token === owner?.token && old?.owner.userId === owner?.userId ? state.verificationLockedUntil || 0 : 0 });
    if (!owner?.token || !id) { publish({ phase: "error" }); failure({ code: "UNAUTHORIZED" }, ctx); return; }
    let recoveryFailed = false;
    try { attempt = recovery.read(owner.userId, id); } catch { recoveryFailed = true; }
    try {
      let order;
      try { order = await api.read(id, ctx.owner, attempt?.key); } catch (error) {
        if (error.code !== "PAYMENT_REQUEST_NOT_FOUND") throw error;
        order = await api.read(id, ctx.owner);
      }
      if (!isCurrent(ctx)) return;
      acceptOrder(order, ctx);
      if (recoveryFailed && order.paymentStatus === "PENDING_PAYMENT") {
        uncertain();
        publish({ message: "无法读取付款恢复标记。请先核实原订单，不要再次付款。" });
      }
    } catch (error) {
      if (!isCurrent(ctx)) return;
      publish({ phase: attempt ? "uncertain" : "error" });
      failure(error, ctx);
      if (attempt && error.code !== "UNAUTHORIZED") publish({ message: "暂时无法核实付款结果，请稍后查询原订单，不要再次付款。" });
    }
  }
  function cancelAuthorization() {
    if (state.phase === "paying") return;
    authEpoch++;
    clearGrant();
    if (["authorizing", "authorized"].includes(state.phase)) publish({ phase: "ready", busy: false, message: "已撤回本次验证。" });
  }
  async function authorize(password) {
    const ctx = context;
    if (!isCurrent(ctx) || state.busy || state.phase !== "ready" || expired(state.order) || state.verificationLockedUntil > now()) return;
    const ticket = ++authEpoch;
    publish({ phase: "authorizing", busy: true, message: "", code: "" });
    try {
      const pending = api.authorize(ctx.id, state.order.version, password, ctx.owner);
      password = "";
      const value = await pending;
      if (!isCurrent(ctx) || ticket !== authEpoch) { await discard(value, ctx); return; }
      if (value.orderId !== ctx.id || value.orderVersion !== state.order.version || value.amount !== state.order.totalPrice
        || value.currency !== "CNY" || value.expiresAt <= now() || expired(state.order)) {
        await discard(value, ctx);
        if (!isCurrent(ctx) || ticket !== authEpoch) return;
        publish({ phase: "ready", busy: false, message: "授权已失效或与当前订单不符，请刷新核对。" });
        return;
      }
      grant = value;
      publish({ phase: "authorized", busy: false, hasAuthorization: true, authorizationExpiresAt: value.expiresAt, message: "验证通过，请核对后明确点击付款。" });
    } catch (error) {
      if (!isCurrent(ctx) || ticket !== authEpoch) return;
      publish({ phase: "ready" });
      failure(error, ctx);
      if (["PRICE_CHANGED", "SALE_NOT_ALLOWED", "QUALIFICATION_CHANGED", "ORDER_EXPIRED", "ORDER_CLOSED", "ORDER_VERSION_CONFLICT"].includes(error.code)) {
        try {
          const order = await api.read(ctx.id, ctx.owner);
          if (isCurrent(ctx) && ticket === authEpoch) acceptOrder(order, ctx);
        } catch {}
      }
    } finally { password = ""; }
  }
  async function pay() {
    const ctx = context;
    if (!isCurrent(ctx) || state.busy || state.phase !== "authorized" || !grant) return;
    if (grant.expiresAt <= now() || expired(state.order)) { cancelAuthorization(); return; }
    const value = grant;
    try {
      attempt ||= { key: makeKey(), version: state.order.version, retryable: false };
      attempt = { ...attempt, retryable: false };
      recovery.write(ctx.owner.userId, ctx.id, attempt);
    } catch {
      clearGrant();
      publish({ phase: "ready", busy: false, message: "无法保存付款恢复标记，本次未发起付款。请允许会话存储后重试。" });
      return;
    }
    grant = null;
    inFlightGrant = value;
    publish({ phase: "paying", busy: true, hasAuthorization: false, message: "正在提交付款，请勿重复操作。" });
    try {
      const receipt = await api.pay(ctx.id, attempt.version, attempt.key, value.token, ctx.owner);
      if (!isCurrent(ctx)) return;
      try { recovery.clear(ctx.owner.userId, ctx.id); } catch {}
      attempt = null;
      publish({ phase: "paid", busy: false, receipt, order: { ...state.order, paymentStatus: "PAID", version: state.order.version + 1 }, message: "" });
    } catch (error) {
      if (!isCurrent(ctx)) return;
      if (error.outcome !== "NOT_APPLIED") {
        uncertain();
        if (error.code === "UNAUTHORIZED") onSessionExpired(ctx.owner);
        return;
      }
      await discard(value, ctx);
      if (!isCurrent(ctx)) return;
      if (error.code === "TRANSACTION_RETRYABLE") {
        attempt.retryable = true;
        try { recovery.write(ctx.owner.userId, ctx.id, attempt); } catch { uncertain(); return; }
      } else {
        try { recovery.clear(ctx.owner.userId, ctx.id); } catch {}
        attempt = null;
      }
      publish({ phase: "ready", busy: false });
      failure(error, ctx);
      try {
        const order = await api.read(ctx.id, ctx.owner);
        if (isCurrent(ctx)) {
          publish({ order });
          if (order.paymentStatus !== "PENDING_PAYMENT") acceptOrder(order, ctx);
        }
      } catch {}
    } finally {
      if (isCurrent(ctx) && inFlightGrant === value) inFlightGrant = null;
    }
  }
  async function close() {
    const ctx = context;
    if (!isCurrent(ctx) || state.busy || !["ready", "authorized"].includes(state.phase)) return;
    clearGrant();
    publish({ phase: "closing", busy: true, message: "" });
    try {
      const order = await api.close(ctx.id, state.order.version, ctx.owner);
      if (isCurrent(ctx)) acceptOrder(order, ctx);
    } catch (error) {
      if (!isCurrent(ctx)) return;
      publish({ phase: "error" });
      failure(error, ctx);
      // Closing never retries a payment; only the explicit refresh action reads again.
    }
  }
  function tick() {
    if (grant && (grant.expiresAt <= now() || expired(state.order))) {
      cancelAuthorization();
      publish({ message: "支付授权或订单已到期，请刷新核对。" });
    }
  }
  function dispose() {
    const old = context;
    epoch++;
    authEpoch++;
    context = null;
    void discard(grant, old);
    void discard(inFlightGrant, old);
    grant = null;
    inFlightGrant = null;
    attempt = null;
    publish({ order: null, receipt: null, phase: "idle", busy: false, hasAuthorization: false, authorizationExpiresAt: 0, verificationLockedUntil: 0, message: "", code: "", cleanupWarning: "" });
  }
  return { load, authorize, cancelAuthorization, pay, close, tick, dispose };
}
