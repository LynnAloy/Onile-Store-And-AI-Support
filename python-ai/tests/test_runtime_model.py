import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.config import Settings
from app.runtime_model import RuntimeModel


class RuntimeModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_reload_and_credentials_not_forwarded(self):
        settings = Settings(service_key="s" * 32, model_api_key="private-key")
        captured = []
        class Fake:
            def __init__(self, client, config): captured.append(config)
            async def stream(self, *args, **kwargs): yield "ok"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            with patch.dict(os.environ, {"AI_CONFIG_PATH": str(path)}), patch("app.runtime_model.OllamaModel", Fake):
                path.write_text(json.dumps({"model": "first", "endpoint": "http://127.0.0.1:11435"}))
                model = RuntimeModel(None, settings)
                self.assertEqual([x async for x in model.stream([])], ["ok"])
                path.write_text(json.dumps({"model": "second", "endpoint": settings.ollama_base_url}))
                self.assertEqual([x async for x in model.stream([])], ["ok"])
        self.assertEqual(captured[0].model, "first")
        self.assertEqual(captured[0].model_api_key, "")
        self.assertEqual(captured[1].model, "second")
        self.assertEqual(captured[1].model_api_key, "")
        self.assertEqual(settings.model_api_key, "private-key")

    async def test_invalid_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text("{broken")
            with patch.dict(os.environ, {"AI_CONFIG_PATH": str(path)}):
                with self.assertRaisesRegex(Exception, "管理员模型配置"):
                    _ = [x async for x in RuntimeModel(None, Settings(service_key="s" * 32)).stream([])]
