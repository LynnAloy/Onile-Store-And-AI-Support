import json
import unittest
import httpx
from app.config import Settings
from app.openai_model import OpenAIModel, chat_messages


def frame(delta, finish=None):
    return "data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]}) + "\n\n"


class OpenAIModelTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, text, tools=None, status=200):
        async def handler(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-key")
            return httpx.Response(status, text=text, headers={"content-type":"text/event-stream"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = Settings(service_key="x"*32, ollama_base_url="https://synthetic.example/v1", model_api_key="synthetic-key")
            return [x async for x in OpenAIModel(client, settings).stream([{"role":"user","content":"hello"}], tools=tools)]

    async def test_text_stream(self):
        result = await self.collect(": ping\n\n" + frame({"content":"你好"}) + frame({},"stop") + "data: [DONE]\n\n")
        self.assertEqual(result, ["你好"])

    async def test_fragmented_tool_arguments_and_history_pairing(self):
        text = frame({"tool_calls":[{"index":0,"id":"a","function":{"name":"get_medicine","arguments":"{\"medicine"}}]})
        text += frame({"tool_calls":[{"index":0,"function":{"arguments":"Id\":1}"}}]},"tool_calls") + "data: [DONE]\n\n"
        result = await self.collect(text, tools=[{"type":"function"}])
        self.assertEqual(result[0]["tool_calls"][0]["function"]["arguments"], {"medicineId":1})
        history = chat_messages([{"role":"assistant","tool_calls":result[0]["tool_calls"]}, {"role":"tool","tool_name":"get_medicine","content":"{}"}], None)
        self.assertEqual(history[1]["tool_calls"][0]["id"], history[2]["tool_call_id"])
        self.assertIsInstance(history[1]["tool_calls"][0]["function"]["arguments"], str)

    async def test_truncated_or_denied_stream_fails(self):
        for text in (frame({"content":"partial"}), frame({},"length") + "data: [DONE]\n\n"):
            with self.assertRaises(Exception): await self.collect(text)
        with self.assertRaises(Exception): await self.collect("provider-error-with-private-data", status=401)
