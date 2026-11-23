import json
import unittest
from types import SimpleNamespace

import httpx

from app.errors import AppError
from app.tools import ReadTools, validated_call


TOKEN = "a" * 43
SETTINGS = SimpleNamespace(java_base_url="http://java", service_key="private-service-key")


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def run_tool(self, handler, name="search_medicines", args=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ReadTools(client, SETTINGS).execute(
                name, args or {"name": "商品", "limit": 5}, TOKEN, "server-generated-trace")

    def test_strict_parameters_prevent_overposting_and_path_injection(self):
        cases = [
            ("search_medicines", {"name": "", "limit": 5}),
            ("search_medicines", {"name": "x", "limit": True}),
            ("search_medicines", {"name": "x", "limit": 11}),
            ("get_medicine", {"medicineId": "1"}),
            ("get_medicine", {"medicineId": 0}),
            ("get_my_order", {"orderId": "../users"}),
            ("get_my_order", {"orderId": "ORD_a", "userId": "bob"}),
            ("pay_order", {}),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args), self.assertRaises(AppError):
                validated_call({"function": {"name": name, "arguments": args}})

    async def test_whitelist_removes_untrusted_extra_fields_and_keeps_money_exact(self):
        async def handle(request):
            self.assertEqual(request.url.params["name"], "商品")
            self.assertEqual(request.headers["X-AI-Service-Key"], SETTINGS.service_key)
            return httpx.Response(200, content=b'[{"id":1,"name":"test","price":0.10,"stock":2,"password":"secret"}]')
        result = await self.run_tool(handle)
        self.assertEqual(result["products"][0]["price"], "0.10")
        self.assertNotIn("secret", json.dumps(result))

    async def test_order_response_is_whitelisted_and_id_bound(self):
        data = {"orderId": "ORD_a", "status": "PAID", "totalPrice": 1.20,
                "recipientPhone": "private", "items": [{"medicineId": 1, "name": "商品",
                "quantity": 1, "price": 1.20, "address": "private"}]}
        result = await self.run_tool(lambda r: httpx.Response(200, json=data),
                                     "get_my_order", {"orderId": "ORD_a"})
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(result["order"]["totalPrice"], "1.20")
        result = await self.run_tool(lambda r: httpx.Response(200, json=data),
                                     "get_my_order", {"orderId": "ORD_b"})
        self.assertEqual(result["code"], "TOOL_RESULT_INVALID")

    async def test_retry_read_failure_is_bounded_and_does_not_expose_server_errors(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(503, text="private sql error")
        result = await self.run_tool(handle)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["code"], "JAVA_UNAVAILABLE")
        self.assertNotIn("private", json.dumps(result))

    async def test_timeout_is_controlled_and_cancel_not_swallowed(self):
        calls = []
        def handle(request):
            calls.append(request)
            raise httpx.ReadTimeout("private host details")
        result = await self.run_tool(handle)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["code"], "JAVA_UNAVAILABLE")
        import asyncio
        async def cancelled(request):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.run_tool(cancelled)

    async def test_revoked_token_not_retried(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(401)
        with self.assertRaises(AppError) as caught:
            await self.run_tool(handle)
        self.assertEqual(caught.exception.code, "UNAUTHORIZED")
        self.assertEqual(len(calls), 1)

    async def test_malformed_and_oversized_results_fail_closed(self):
        bodies = [
            b"x" * 32769,
            b'{"products":[]}',
            b'[{"id":1,"name":"x","price":-2,"stock":1}]',
            b'[{"id":1,"name":"x","price":1.234,"stock":1}]',
            b'[{"id":1,"name":"x","price":1,"stock":-1}]',
        ]
        for body in bodies:
            result = await self.run_tool(lambda r: httpx.Response(200, content=body))
            self.assertEqual(result["code"], "TOOL_RESULT_INVALID")

    async def test_no_result_is_valid_not_found_product_list(self):
        result = await self.run_tool(lambda r: httpx.Response(200, json=[]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["products"], [])

