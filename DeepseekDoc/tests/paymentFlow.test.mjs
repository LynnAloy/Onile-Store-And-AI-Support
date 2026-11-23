import test from "node:test";
import assert from "node:assert/strict";
import { createPaymentFlow } from "../src/services/paymentFlow.mjs";
import { createPaymentRecovery, browserPaymentRecovery } from "../src/services/paymentRecovery.mjs";
import { createPaymentClient } from "../src/services/paymentClient.mjs";

const order = () => ({ orderId: "ORD_test", version: 1, paymentStatus: "PENDING_PAYMENT", totalPrice: "2.50", currency: "CNY", expiresAt: 1000, items: [] });
const authorization = id => ({ authorizationId: id, token: "secret-capability-" + id, orderId: "ORD_test", orderVersion: 1, amount: "2.50", currency: "CNY", expiresAt: 160 });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function setup(overrides = {}) {
  let owner = { userId: "alice", token: "alice-parent" };
  let time = 100;
  let state;
  let key = 0;
  const entries = new Map();
  const storage = { getItem: key => entries.get(key) || null, setItem: (key, value) => entries.set(key, value), removeItem: key => entries.delete(key) };
  const recovery = createPaymentRecovery(storage);
  const calls = [];
  const expired = [];
  const api = {};
  const implementations = {
    read: async () => order(), authorize: async () => authorization("grant-one"), revoke: async () => ({ revoked: true }),
    pay: async () => ({ paymentId: "PAY_one", orderId: "ORD_test", amount: "2.50", currency: "CNY", paidAt: time }),
    close: async () => ({ ...order(), paymentStatus: "CLOSED", version: 2 }), ...overrides,
  };
  for (const [name, implementation] of Object.entries(implementations)) {
    api[name] = (...args) => { calls.push({ name, args }); return implementation(...args); };
  }
  const options = { api, getOwner: () => owner, recovery, onChange: value => { state = value; }, now: () => time,
    makeKey: () => `payment-key-${++key}`, onSessionExpired: value => expired.push(value) };
  const flow = createPaymentFlow(options);
  return { flow, options, recovery, storage, entries, calls, expired, state: () => state,
    switchOwner: value => { owner = value; }, clock: value => { time = value; } };
}

test("verification and explicit payment are separate; double clicks send once and state contains no credentials", async () => {
  const pending = deferred();
  const h = setup({ pay: () => pending.promise });
  await h.flow.load("ORD_test");
  await h.flow.authorize("secret-pin");
  assert.equal(h.calls.filter(c => c.name === "pay").length, 0);
  assert.equal(h.state().phase, "authorized");
  assert.ok(!JSON.stringify(h.state()).includes("secret-"));
  const first = h.flow.pay();
  await h.flow.pay();
  assert.equal(h.calls.filter(c => c.name === "pay").length, 1);
  assert.ok(h.recovery.read("alice", "ORD_test"));
  pending.resolve({ paymentId: "PAY_one" });
  await first;
  assert.equal(h.state().phase, "paid");
  assert.equal(h.recovery.read("alice", "ORD_test"), null);
});

test("late verification after cancellation revokes only its own grant and preserves newer authorization", async () => {
  const pending = deferred();
  let count = 0;
  const h = setup({ authorize: () => ++count === 1 ? pending.promise : Promise.resolve(authorization("new")) });
  await h.flow.load("ORD_test");
  const first = h.flow.authorize("pin");
  h.flow.cancelAuthorization();
  await h.flow.authorize("pin");
  pending.resolve(authorization("late"));
  await first;
  assert.equal(h.state().phase, "authorized");
  assert.deepEqual(h.calls.filter(c => c.name === "revoke").map(c => c.args[1]), ["late"]);
  await h.flow.pay();
  assert.equal(h.calls.find(c => c.name === "pay").args[3], "secret-capability-new");
});

test("account switch discards late grant with original identity and never expires new account", async () => {
  const pending = deferred();
  const h = setup({ authorize: () => pending.promise });
  await h.flow.load("ORD_test");
  const issued = h.flow.authorize("pin");
  h.switchOwner({ userId: "bob", token: "bob-parent" });
  h.flow.dispose();
  pending.resolve(authorization("late"));
  await issued;
  const cleanup = h.calls.find(c => c.name === "revoke");
  assert.equal(cleanup.args[2].token, "alice-parent");
  assert.equal(h.state().order, null);
  assert.equal(h.expired.length, 0);
});

test("stale authorization errors after route change cannot change next order or login", async () => {
  const pending = deferred();
  const h = setup({ authorize: () => pending.promise });
  await h.flow.load("ORD_test");
  const issued = h.flow.authorize("pin");
  h.flow.dispose();
  await h.flow.load("ORD_next");
  pending.reject(Object.assign(new Error("old session"), { code: "UNAUTHORIZED" }));
  await issued;
  assert.equal(h.state().phase, "ready");
  assert.equal(h.expired.length, 0);
});

test("lost payment response remains uncertain across reload and never resends or reauthorizes", async () => {
  const h = setup({ pay: async () => { throw Object.assign(new Error("offline"), { outcome: "UNKNOWN" }); } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  await h.flow.pay();
  assert.equal(h.state().phase, "uncertain");
  h.flow.dispose();
  const restored = createPaymentFlow(h.options);
  await restored.load("ORD_test");
  assert.equal(h.state().phase, "uncertain");
  await restored.authorize("pin");
  await restored.pay();
  await restored.close();
  assert.equal(h.calls.filter(c => c.name === "pay").length, 1);
  assert.equal(h.calls.filter(c => c.name === "authorize").length, 1);
  assert.ok(h.calls.filter(c => c.name === "read").at(-1).args[2].startsWith("payment-key-"));
});

test("recovery of committed payment clears marker with GET and displays receipt", async () => {
  const h = setup({ read: async () => ({ ...order(), paymentStatus: "PAID", version: 2, payment: { paymentId: "PAY_recovered" } }) });
  h.recovery.write("alice", "ORD_test", { key: "lost-payment", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "paid");
  assert.equal(h.state().receipt.paymentId, "PAY_recovered");
  assert.equal(h.recovery.read("alice", "ORD_test"), null);
  assert.deepEqual(h.calls.map(c => c.name), ["read"]);
});

test("missing request registration is still uncertain; fallback reads only the same order", async () => {
  const h = setup({ read: async (id, owner, key) => {
    if (key) throw { code: "PAYMENT_REQUEST_NOT_FOUND" };
    return order();
  } });
  h.recovery.write("alice", "ORD_test", { key: "lost-payment", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "uncertain");
  assert.deepEqual(h.calls.map(c => c.name), ["read", "read"]);
});

test("explicit rejection is recoverable without any automatic POST", async () => {
  const h = setup({ read: async () => ({ ...order(), requestOutcome: { status: "REJECTED", code: "OUT_OF_STOCK" } }) });
  h.recovery.write("alice", "ORD_test", { key: "old-rejected", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "ready");
  assert.match(h.state().message, /库存不足/);
  assert.equal(h.recovery.read("alice", "ORD_test"), null);
  assert.deepEqual(h.calls.map(c => c.name), ["read"]);
});

test("proven rollback keeps original request key across refresh; retry still requires explicit verification and pay", async () => {
  let number = 0;
  const h = setup({ pay: async () => {
    if (++number === 1) throw { code: "TRANSACTION_RETRYABLE", outcome: "NOT_APPLIED" };
    return { paymentId: "PAY_retry" };
  } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  await h.flow.pay();
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "ready");
  assert.equal(h.calls.filter(c => c.name === "pay").length, 1);
  await h.flow.authorize("pin");
  await h.flow.pay();
  const payments = h.calls.filter(c => c.name === "pay");
  assert.equal(payments[0].args[2], payments[1].args[2]);
  assert.equal(h.state().phase, "paid");
});

test("expired or mismatched late authorization never becomes payable", async () => {
  const h = setup({ authorize: async () => ({ ...authorization("expired"), expiresAt: 99 }) });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  assert.equal(h.state().phase, "ready");
  await h.flow.pay();
  assert.equal(h.calls.filter(c => c.name === "pay").length, 0);
  assert.equal(h.calls.find(c => c.name === "revoke").args[1], "expired");
});

test("grant expiry and page disposal clear capabilities and revoke only captured owner/order", async () => {
  const h = setup();
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  h.clock(161);
  h.flow.tick();
  assert.equal(h.state().hasAuthorization, false);
  assert.equal(h.state().phase, "ready");
  assert.equal(h.calls.filter(c => c.name === "revoke").length, 1);
});

test("storage unavailable blocks payment before sending financial request", async () => {
  const h = setup();
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  h.storage.setItem = () => { throw new Error("quota"); };
  await h.flow.pay();
  assert.match(h.state().message, /本次未发起付款/);
  assert.equal(h.calls.filter(c => c.name === "pay").length, 0);
});

test("leaving during payment retains recovery marker and ignores late paid response", async () => {
  const pending = deferred();
  const h = setup({ pay: () => pending.promise });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  const paid = h.flow.pay();
  h.flow.dispose();
  pending.resolve({ paymentId: "PAY_late" });
  await paid;
  assert.equal(h.state().order, null);
  assert.equal(h.state().receipt, null);
  assert.ok(h.recovery.read("alice", "ORD_test"));
  assert.equal(h.calls.find(c => c.name === "revoke").args[2].token, "alice-parent");
});

test("password failure never expires a valid USER session; no implicit retry", async () => {
  const h = setup({ authorize: async () => { throw { code: "PAYMENT_VERIFICATION_FAILED", outcome: "NOT_APPLIED" }; } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("wrong-pin");
  assert.equal(h.state().phase, "ready");
  assert.equal(h.expired.length, 0);
  assert.equal(h.calls.filter(c => c.name === "authorize").length, 1);
});

test("recovery storage excludes all capabilities and isolates users; draft checkout key survives refresh", () => {
  const h = setup();
  h.recovery.write("alice", "ORD_test", { key: "payment-key-one", version: 1, token: "do-not-persist", password: "do-not-persist" });
  assert.equal(h.recovery.read("bob", "ORD_test"), null);
  assert.ok(!JSON.stringify([...h.entries]).includes("do-not-persist"));
  const first = h.recovery.checkoutKey("alice", "draft", 2, () => "checkout-key-one");
  assert.equal(h.recovery.checkoutKey("alice", "draft", 2, () => assert.fail("Changed key")), first);
});

test("owner-bound transport preserves PIN spaces, separates authorization header and refuses redirects", async () => {
  const calls = [];
  const api = createPaymentClient({ fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  } });
  const original = { userId: "alice", token: "old-parent" };
  await api.authorize("ORD_test", 1, " 123456 ", original);
  await api.pay("ORD_test", 1, "payment-key", "grant-secret", original);
  await api.revoke("ORD_test", "exact-authorization", original);
  assert.equal(JSON.parse(calls[0].options.body).password, " 123456 ");
  assert.equal(calls[0].options.redirect, "error");
  assert.equal(calls[1].options.headers["X-Payment-Authorization"], "grant-secret");
  assert.equal(calls[1].options.headers.Authorization, "Bearer old-parent");
  assert.deepEqual(JSON.parse(calls[1].options.body), { expectedVersion: 1 });
  assert.match(calls[2].url, /authorizationId=exact-authorization/);
});

test("late scoped revoke accepts expired original session without touching another account", async () => {
  const api = createPaymentClient({ fetchImpl: async () => new Response(JSON.stringify({ code: "UNAUTHORIZED" }), { status: 401 }) });
  await api.revoke("ORD_old", "old-grant", { token: "old-parent" });
});

test("expired grant cleanup finishing after account switch cannot overwrite the next page", async () => {
  const pending = deferred();
  const h = setup({ authorize: async () => ({ ...authorization("expired"), expiresAt: 99 }), revoke: () => pending.promise });
  await h.flow.load("ORD_test");
  const issued = h.flow.authorize("pin");
  await Promise.resolve();
  h.switchOwner({ userId: "bob", token: "bob-parent" });
  await h.flow.load("ORD_next");
  pending.resolve({ revoked: true });
  await issued;
  assert.equal(h.state().message, "");
  assert.equal(h.state().phase, "ready");
});

test("payment session expiry preserves recovery marker and expires only current captured session", async () => {
  const h = setup({ pay: async () => { throw { code: "UNAUTHORIZED", status: 401 }; } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  await h.flow.pay();
  assert.deepEqual(h.expired, [{ userId: "alice", token: "alice-parent" }]);
  assert.ok(h.recovery.read("alice", "ORD_test"));
});

test("catalog rejection during verification reads the terminal order without retrying credentials", async () => {
  let reads = 0;
  const h = setup({ read: async () => ++reads === 1 ? order() : { ...order(), paymentStatus: "CLOSED", closeReason: "CATALOG_CHANGED" },
    authorize: async () => { throw { code: "PRICE_CHANGED", outcome: "NOT_APPLIED" }; } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  assert.equal(h.state().phase, "closed");
  assert.equal(h.calls.filter(c => c.name === "authorize").length, 1);
});

test("malformed recovery storage fails closed while still allowing order lookup", async () => {
  const h = setup();
  h.storage.getItem = () => "broken-json";
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "uncertain");
  assert.equal(h.calls.filter(c => c.name === "read").length, 1);
  await h.flow.authorize("pin");
  assert.equal(h.calls.filter(c => c.name === "authorize").length, 0);
});

test("REGISTERED alone never proves a timed-out payment was rolled back", async () => {
  const h = setup({ read: async () => ({ ...order(), requestOutcome: { status: "REGISTERED" } }) });
  h.recovery.write("alice", "ORD_test", { key: "registered-only", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "uncertain");
  assert.ok(h.recovery.read("alice", "ORD_test"));
});

test("non-JSON gateway response remains UNKNOWN rather than a false unpaid result", async () => {
  const api = createPaymentClient({ fetchImpl: async () => new Response("gateway", { status: 502 }) });
  await assert.rejects(api.pay("ORD_test", 1, "original-key", "grant", { token: "parent" }), error => error.outcome === "UNKNOWN");
});

test("verification lock respects Retry-After without implicit requests", async () => {
  const h = setup({ authorize: async () => { throw { code: "RATE_LIMITED", retryAfter: 900 }; } });
  await h.flow.load("ORD_test");
  await h.flow.authorize("pin");
  assert.equal(h.state().verificationLockedUntil, 1000);
  await h.flow.authorize("pin");
  assert.equal(h.calls.filter(c => c.name === "authorize").length, 1);
  h.flow.dispose();
  assert.equal(h.state().verificationLockedUntil, 0);
});

test("unavailable browser storage does not throw during page setup", () => {
  const recovery = browserPaymentRecovery();
  assert.throws(() => recovery.read("alice", "ORD_test"));
});

test("background-fenced abandoned request returns to verification but never automatically pays", async () => {
  const h = setup({ read: async () => ({ ...order(), requestOutcome: { status: "REJECTED", code: "PAYMENT_ATTEMPT_EXPIRED" } }) });
  h.recovery.write("alice", "ORD_test", { key: "abandoned-key", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "ready");
  assert.match(h.state().message, /已核实未执行/);
  assert.deepEqual(h.calls.map(c => c.name), ["read"]);
  await h.flow.authorize("pin");
  await h.flow.pay();
  assert.notEqual(h.calls.find(c => c.name === "pay").args[2], "abandoned-key");
});

test("unavailable recovery service preserves UNKNOWN rather than showing a false failure", async () => {
  const h = setup({ read: async () => { throw new Error("gateway error"); } });
  h.recovery.write("alice", "ORD_test", { key: "original-payment", version: 1 });
  await h.flow.load("ORD_test");
  assert.equal(h.state().phase, "uncertain");
  assert.match(h.state().message, /不要再次付款/);
  assert.ok(h.recovery.read("alice", "ORD_test"));
});
