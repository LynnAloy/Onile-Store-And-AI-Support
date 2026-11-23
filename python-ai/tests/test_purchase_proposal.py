import unittest
from app.purchase_proposal import propose_purchase
from app.tools import tool_schemas


PRODUCTS = {
    3: {"id": 3, "name": "枇杷露", "price": "12.00", "stock": 8, "currency": "CNY",
        "draftEligible": False, "draftBlockedReason": "商品销售资格尚未审核通过"},
    1: {"id": 1, "name": "布洛芬", "price": "8.00", "stock": 50, "currency": "CNY",
        "draftEligible": False, "draftBlockedReason": "商品销售资格尚未审核通过"},
}
TERMS = {"枇杷露": {3}, "布洛芬": {1}}


class PurchaseProposalTests(unittest.TestCase):
    def test_read_only_request_does_not_trigger_purchase_reminder(self):
        from app.purchase_proposal import is_purchase_request
        self.assertFalse(is_purchase_request("只查询，不要购买"))
        self.assertFalse(is_purchase_request("我不想买，只查价格"))
        self.assertTrue(is_purchase_request("帮我下单2件虚构演示甲，不要付款"))

    def test_preview_fallback_requires_every_literal_clause_to_match_exactly(self):
        from app.purchase_proposal import grounded_fallback_args
        products = {4: {"name": "虚构待审核"}}
        self.assertEqual(grounded_fallback_args("帮我下单2件虚构待审核", products),
                         {"items": [{"medicineId": 4, "quantity": 2}]})
        self.assertIsNone(grounded_fallback_args("帮我下单2件虚构待审核，3件不存在商品", products))
        self.assertIsNone(grounded_fallback_args("帮我下单2件虚构", products))
        self.assertEqual(grounded_fallback_args("我想购买虚构待审核，数量还未决定", products),
                         {"items": [{"medicineId": 4, "quantity": None}]})

    def test_ambiguous_catalog_stops_for_choice_without_splitting_quantity(self):
        from app.purchase_proposal import ambiguous_catalog_reply
        products = {4: {"name": "虚构多规格小"}, 5: {"name": "虚构多规格大"}}
        reply = ambiguous_catalog_reply("我想购买2件虚构多规格，规格未决定", products, {"虚构多规格": {4, 5}})
        self.assertIn("数量为2件", reply)
        self.assertIn("不能自行拆分", reply)
        self.assertIsNone(ambiguous_catalog_reply("我想购买2件虚构多规格小", products, {"虚构多规格小": {4}}))

    def test_truncated_keyword_cannot_replace_another_requested_product(self):
        products = {4: {**PRODUCTS[3], "id": 4, "name": "虚构演示甲"}}
        result = propose_purchase({"items": [{"medicineId": 4, "quantity": 2}]},
                                  "帮我下单2件虚构待审核", products, {"虚构": {4}})
        self.assertFalse(result["ok"])

    def test_preview_and_authorized_prepare_are_distinct_tool_phases(self):
        preview = {entry["function"]["name"] for entry in tool_schemas(False)}
        prepare = {entry["function"]["name"] for entry in tool_schemas(True)}
        self.assertIn("propose_purchase", preview)
        self.assertNotIn("prepare_order_draft", preview)
        self.assertIn("prepare_order_draft", prepare)
        self.assertNotIn("propose_purchase", prepare)
    def test_exact_user_quantities_survive_unreviewed_qualification(self):
        args = {"items": [{"medicineId": 3, "quantity": 5, "evidence": "5件枇杷露"},
                          {"medicineId": 1, "quantity": 3, "evidence": "3件布洛芬"}]}
        result = propose_purchase(args, "帮我下单5件枇杷露，3件布洛芬", PRODUCTS, TERMS)
        self.assertTrue(result["ok"])
        self.assertEqual([item["quantity"] for item in result["proposal"]["items"]], [5, 3])
        self.assertTrue(all(item["autoSelect"] for item in result["proposal"]["items"]))
        self.assertFalse(any(item["draftEligible"] for item in result["proposal"]["items"]))
        self.assertTrue(result["proposal"]["requiresUserAuthorization"])

    def test_quantities_cannot_be_swapped_in_a_whole_sentence_quote(self):
        message = "帮我下单5件枇杷露，3件布洛芬"
        result = propose_purchase({"items": [{"medicineId": 1, "quantity": 5, "evidence": message}]},
                                  message, PRODUCTS, TERMS)
        self.assertFalse(result["ok"])

    def test_native_calls_without_optional_quote_are_grounded_in_current_message(self):
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": 5},
                                            {"medicineId": 1, "quantity": 3}]},
                                  "帮我下单5件枇杷露，3件布洛芬", PRODUCTS, TERMS)
        self.assertTrue(result["ok"])
        wrong = propose_purchase({"items": [{"medicineId": 1, "quantity": 5}]},
                                 "帮我下单5件枇杷露，3件布洛芬", PRODUCTS, TERMS)
        self.assertFalse(wrong["ok"])

    def test_unseen_product_or_invented_quote_cannot_enter_selection(self):
        for line in ({"medicineId": 999, "quantity": 5, "evidence": "5件枇杷露"},
                     {"medicineId": 3, "quantity": 6, "evidence": "6件枇杷露"}):
            self.assertFalse(propose_purchase({"items": [line]}, "5件枇杷露", PRODUCTS, TERMS)["ok"])

    def test_missing_quantity_is_not_defaulted_to_one(self):
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": None, "evidence": "枇杷露"}]},
                                  "我想买枇杷露", PRODUCTS, TERMS)
        item = result["proposal"]["items"][0]
        self.assertIsNone(item["quantity"])
        self.assertEqual(item["quantitySource"], "missing")

    def test_literal_quantity_is_recovered_if_model_omits_it(self):
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": None, "evidence": "枇杷露"}]},
                                  "帮我买五件枇杷露", PRODUCTS, TERMS)
        self.assertEqual(result["proposal"]["items"][0]["quantity"], 5)

    def test_multiple_variants_require_product_confirmation(self):
        products = {**PRODUCTS, 4: {**PRODUCTS[3], "id": 4, "name": "另一规格枇杷露"}}
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": 5, "evidence": "5件枇杷露"}]},
                                  "买5件枇杷露", products, {"枇杷露": {3, 4}})
        self.assertFalse(result["proposal"]["items"][0]["autoSelect"])

    def test_two_digit_quantities_and_postfix_units_are_bound_correctly(self):
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": 15, "evidence": "枇杷露要15瓶"}]},
                                  "枇杷露要15瓶", PRODUCTS, TERMS)
        self.assertEqual(result["proposal"]["items"][0]["quantity"], 15)
        result = propose_purchase({"items": [{"medicineId": 3, "quantity": 5, "evidence": "15瓶枇杷露"}]},
                                  "15瓶枇杷露", PRODUCTS, TERMS)
        self.assertFalse(result["ok"])

