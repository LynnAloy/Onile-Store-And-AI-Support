import test from "node:test";
import assert from "node:assert/strict";
import { consumeOrderGrant, issueOwnerBoundOrderGrant } from "../src/services/orderAuthorization.mjs";

test("grant issuance carries the captured owner rather than a later account token", async () => {
  const items = [{ medicineId: 4, quantity: 5 }];
  let observed;
  const result = await issueOwnerBoundOrderGrant({ items }, "original-owner", {
    fetchImpl: async (url, options) => {
      observed = { url, options };
      return new Response(JSON.stringify({ requestKey: "original-request" }), { status: 200 });
    },
  });
  assert.equal(observed.options.headers.Authorization, "Bearer original-owner");
  assert.deepEqual(JSON.parse(observed.options.body), { items });
  assert.equal(result.requestKey, "original-request");
});

test("revoke while grant response is pending discards exactly that late grant", async () => {
  let resolve;
  let current = true;
  const discarded = [];
  let uses = 0;
  const pending = consumeOrderGrant({ issue: () => new Promise(done => { resolve = done; }),
    isCurrent: () => current, discard: async grant => discarded.push(grant.requestKey),
    use: () => { uses++; } });
  current = false;
  resolve({ requestKey: "old-request" });
  await pending;
  assert.deepEqual(discarded, ["old-request"]);
  assert.equal(uses, 0);
});

test("current explicit authorization is consumed once", async () => {
  let uses = 0;
  await consumeOrderGrant({ issue: async () => ({ requestKey: "current" }), isCurrent: () => true,
    discard: () => assert.fail("Valid authorization was discarded"), use: () => { uses++; } });
  assert.equal(uses, 1);
});

test("failure to discard a stale grant never permits a draft request", async () => {
  await assert.rejects(consumeOrderGrant({ issue: async () => ({ requestKey: "stale" }),
    isCurrent: () => false, discard: async () => { throw new Error("network failure"); },
    use: () => assert.fail("Stale grant was used") }), /network failure/);
});
