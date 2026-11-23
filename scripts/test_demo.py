import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import local_stack as stack


class DemoSafetyTests(unittest.TestCase):
    def test_stop_refuses_same_project_pid_from_other_environment(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            import json
            run = Path(directory)
            (run / "stack.json").write_text(json.dumps({"frontend": {"pid": 12345}}))
            fake = subprocess.CompletedProcess([], 0, stdout=str(stack.ROOT) + "/vite.js --port 3000")
            with patch.object(stack, "RUN", run), patch.object(stack, "FRONT_PORT", 13000):
                with patch.object(stack.subprocess, "run", return_value=fake) as execute:
                    with self.assertRaisesRegex(RuntimeError, "another environment"):
                        stack.stop()
                    self.assertEqual(execute.call_count, 1)

    def test_crash_manifest_records_owned_ids_without_credentials(self):
        import json
        import live_smoke
        smoke = object.__new__(live_smoke.Smoke)
        smoke.prefix = "it_owned"
        smoke.created_names = ["it_owned_a"]
        smoke.conn = MagicMock()
        smoke.values = {"DB_NAME": "DeepseekDoc_M43_Demo", "DB_USERNAME": "demo", "DB_PASSWORD": "do-not-write"}
        smoke.product = 7
        smoke.product_name = "synthetic product"
        smoke.card, smoke.card_b = "card-a", "card-b"
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live_smoke, "RUN", Path(directory)):
                with patch.object(live_smoke, "query", return_value=(("owned-uuid",),)):
                    smoke.persist_fixture()
            text = smoke.fixture_path.read_text(encoding="utf-8")
            self.assertNotIn("do-not-write", text)
            self.assertEqual(json.loads(text)["users"], [{"name": "it_owned_a", "id": "owned-uuid"}])
            self.assertFalse(smoke.fixture_path.with_suffix(".tmp").exists())

    def test_demo_config_rejects_normal_database_even_with_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "demo.env"
            config.write_text("DB_NAME=DeepseekDoc_M43_Demo\n", encoding="utf-8")
            with patch.object(stack, "CONFIG", config), patch.object(stack, "DEMO", True):
                with patch.dict(os.environ, {"DB_NAME": "DeepSeekDoc"}):
                    with self.assertRaisesRegex(RuntimeError, "dedicated"):
                        stack.config()

    def test_normal_config_still_accepts_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "normal.env"
            config.write_text("DB_NAME=DeepSeekDoc\n", encoding="utf-8")
            with patch.object(stack, "CONFIG", config), patch.object(stack, "DEMO", False):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(stack.config()["DB_NAME"], "DeepSeekDoc")

    def test_reset_does_not_stop_or_delete_without_marker(self):
        # Importing demo sets the process-local selector; restore it after the test.
        old = os.environ.get("DEEPSEEKDOC_DEMO")
        import demo
        if old is None:
            os.environ.pop("DEEPSEEKDOC_DEMO", None)
        else:
            os.environ["DEEPSEEKDOC_DEMO"] = old
        with patch.object(demo, "guard", side_effect=RuntimeError("marker mismatch")):
            with patch.object(stack, "stop") as stop, patch.object(stack, "database") as connect:
                with self.assertRaisesRegex(RuntimeError, "marker"):
                    demo.reset()
                stop.assert_not_called()
                connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
