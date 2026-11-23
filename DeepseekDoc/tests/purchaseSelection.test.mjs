import test from "node:test";
import assert from "node:assert/strict";
import { canSelectProduct, selectionBlockers, proposalSelection } from "../src/services/purchaseSelection.mjs";
import { validToolEvent } from "../src/services/toolEvents.mjs";

const products = [
  { id: 3, name: "枇杷露", price: "12.00", stock: 8, currency: "CNY", draftEligible: false,
    draftBlockedReason: "商品销售资格尚未审核通过", quantity: 5, quantitySource: "explicit", autoSelect: true },
  { id: 1, name: "布洛芬", price: "8.00", stock: 50, currency: "CNY", draftEligible: false,
    draftBlockedReason: "商品销售资格尚未审核通过", quantity: 3, quantitySource: "explicit", autoSelect: true },
];

test("unreviewed items remain selectable while draft authorization is blocked", () => {
  assert.equal(canSelectProduct(products[0], []), true);
  const selected = [products[0]];
  assert.equal(canSelectProduct(products[0], selected), true);
  assert.deepEqual(selectionBlockers(selected, { 3: 5 }), ["枇杷露：商品销售资格尚未审核通过"]);
  assert.equal(canSelectProduct(products[0], selected, true), false);
});

test("structured proposal fills 5 and 3 without granting permission or changing eligibility", () => {
  const proposal = { items: products, requiresUserAuthorization: true, snapshot: true };
  const selection = proposalSelection(proposal);
  assert.deepEqual(selection.quantities, { 3: 5, 1: 3 });
  assert.equal(selection.products.length, 2);
  assert.equal(selectionBlockers(selection.products, selection.quantities).length, 2);
  assert.equal(validToolEvent("tool_result", { callId: "call-proposal", tool: "propose_purchase",
    status: "completed", durationMs: 20, result: { ok: true, proposal } }), true);
});

test("missing quantity and insufficient stock never silently become a valid one-item order", () => {
  const product = { ...products[0], draftEligible: true, draftBlockedReason: "", quantity: null };
  const selection = proposalSelection({ items: [product], requiresUserAuthorization: true });
  assert.equal(selection.quantities[3], null);
  assert.match(selectionBlockers(selection.products, selection.quantities)[0], /整数数量/);
  assert.match(selectionBlockers(selection.products, { 3: 9 })[0], /库存不足/);
});

test("ambiguous variants preserve quantity but require explicit selection", () => {
  const proposal = { items: [{ ...products[0], autoSelect: false }], requiresUserAuthorization: true };
  const selection = proposalSelection(proposal);
  assert.equal(selection.products.length, 0);
  assert.equal(selection.quantities[3], 5);
});

