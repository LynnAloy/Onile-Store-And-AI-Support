import test from "node:test";
import assert from "node:assert/strict";
import { createCommerceClient, fulfillAutoProposal } from "../src/services/commerceClient.mjs";

const owner = { token: "original-owner", userId: "alice" };
const turn = { status: "READY", turnId: "turn-original" };
const proposal = { items: [{ id: 1, quantity: 2, stock: 10, draftEligible: true, autoSelect: true }] };

test("auto order uses captured owner and original turn exactly once", async () => {
  const calls = [];
  const client = { execute: async (...args) => { calls.push(args); return { status: "PAID", orderId: "one" }; } };
  const result = await fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client });
  assert.equal(result.status, "PAID");
  assert.deepEqual(calls, [["turn-original", [{ medicineId: 1, quantity: 2 }], owner]]);
});

test("late session callback, manual mode and invalid proposal never spend", async () => {
  const client = { execute: () => assert.fail("must not spend") };
  await fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => false, client });
  await fulfillAutoProposal({ proposal, turn: { status: "MANUAL" }, owner, isCurrent: () => true, client });
  for (const changed of [{ autoSelect: false }, { draftEligible: false }, { quantity: null }, { quantity: 100 }, { stock: 1 }]) {
    const result = await fulfillAutoProposal({ proposal: { items: [{ ...proposal.items[0], ...changed }] }, turn, owner, isCurrent: () => true, client });
    assert.equal(result.status, "MANUAL");
  }
});

test("uncertain commit only reads the same turn without retrying financial write", async () => {
  let writes = 0;
  const client = {
    execute: async () => { writes++; throw Object.assign(new Error("timeout"), { outcome: "UNKNOWN" }); },
    read: async (id, captured) => { assert.equal(id, turn.turnId); assert.equal(captured, owner); return { status: "PAID", orderId: "committed" }; },
  };
  const result = await fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client });
  assert.equal(result.orderId, "committed"); assert.equal(writes, 1);
  client.read = async () => ({ status: "READY" });
  assert.equal((await fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client })).status, "UNKNOWN");
  assert.equal(writes, 2);
});

test("known refusal never retries or falls back to manual payment automatically", async () => {
  const error = Object.assign(new Error("limit"), { outcome: "NOT_APPLIED" });
  const client = { execute: async () => { throw error; }, read: () => assert.fail("unnecessary read") };
  await assert.rejects(fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client }), /limit/);
});

test("commerce requests never follow redirects or borrow another session", async () => {
  const calls = [];
  const client = createCommerceClient({ fetchImpl: async (...args) => {
    calls.push(args); return { ok: true, json: async () => ({ status: "PAID" }) };
  } });
  await client.execute("original", [{ medicineId: 1, quantity: 2 }], owner);
  const [path, request] = calls[0];
  assert.equal(path, "/api/auto-orders/turns/original/execute");
  assert.equal(request.headers.Authorization, "Bearer original-owner");
  assert.equal(request.redirect, "error"); assert.equal(request.cache, "no-store");
  assert.equal(request.body, '{"items":[{"medicineId":1,"quantity":2}]}');
});

test("read failure cannot downgrade an unknown financial outcome", async () => {
  for (const failure of [{ status: 401, outcome: "NOT_APPLIED" }, { status: 503, outcome: "NOT_APPLIED" }]) {
    const client = {
      execute: async () => { throw Object.assign(new Error("lost response"), { outcome: "UNKNOWN" }); },
      read: async () => { throw Object.assign(new Error("query failed"), failure); },
    };
    await assert.rejects(fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client }), error => error.outcome === "UNKNOWN" && error.turnId === turn.turnId);
  }
});
test("health review can never be bypassed by the browser coordinator", async () => {
  const result = await fulfillAutoProposal({ proposal: { ...proposal, riskAssessment: { automaticPurchaseAllowed: false } }, turn, owner, isCurrent: () => true, client: { execute: () => assert.fail("must not spend") } });
  assert.equal(result.status, "MANUAL");
});

test("only an actual automatic write records a recovery identity", async () => {
  const calls = [];
  const options = { proposal, turn, owner, isCurrent: () => true,
    onAttempt: id => calls.push(['remember', id]), client: { execute: async () => { calls.push(['execute']); return { status: 'PAID' }; } } };
  await fulfillAutoProposal(options);
  assert.deepEqual(calls, [['remember', turn.turnId], ['execute']]);
  calls.length = 0;
  await fulfillAutoProposal({ ...options, proposal: { ...proposal, riskAssessment: { automaticPurchaseAllowed: false } } });
  assert.deepEqual(calls, []);
});

test("unclassified gateway failure of a financial write remains unknown", async () => {
  const client = createCommerceClient({ fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({ code: 'PROXY_FAILURE' }) }) });
  await assert.rejects(client.execute(turn.turnId, [{ medicineId: 1, quantity: 1 }], owner), error => error.outcome === 'UNKNOWN');
});
test("a nonterminal write response only triggers an original-turn read", async () => {
  const events = [];
  const client = { execute: async () => { events.push('write'); return { status: 'READY' }; }, read: async id => { events.push(id); return { status: 'PAID' }; } };
  assert.equal((await fulfillAutoProposal({ proposal, turn, owner, isCurrent: () => true, client })).status, 'PAID');
  assert.deepEqual(events, ['write', turn.turnId]);
});
