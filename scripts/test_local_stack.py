import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_stack as stack


class LocalStackSafetyTests(unittest.TestCase):
    def test_fixture_cleanup_never_uses_names_without_successful_registration(self):
        from unittest.mock import MagicMock
        import live_smoke
        smoke = object.__new__(live_smoke.Smoke)
        smoke.names = ["existing-account-a", "existing-account-b"]
        smoke.created_names = []
        smoke.http = MagicMock()
        smoke.conn = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live_smoke, "RUN", Path(directory)):
                with patch.object(live_smoke, "query") as query:
                    smoke.cleanup()
                    query.assert_not_called()
        smoke.http.close.assert_called_once()
        smoke.conn.close.assert_called_once()

    def test_model_directory_must_contain_the_selected_model(self):
        from unittest.mock import MagicMock
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.return_value = stack.httpx.Response(
            200, json={"models": [{"name": "Qwen2.5:latest"}]},
            request=stack.httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
        )
        with patch.object(stack.httpx, "Client", return_value=client):
            self.assertEqual(stack.check_model({"OLLAMA_MODEL": "qwen2.5"}), "Qwen2.5:latest")
            with self.assertRaisesRegex(RuntimeError, "not available"):
                stack.check_model({"OLLAMA_MODEL": "missing:latest"})

    def test_initialize_never_overwrites_an_existing_database(self):
        from unittest.mock import MagicMock
        connection = MagicMock()
        connection.__enter__.return_value = connection
        values = {"DB_USERNAME": "demo", "DB_PASSWORD": "secret", "DB_NAME": "DeepSeekDoc"}
        with patch.object(stack, "ensure_private"), patch.object(stack, "config", return_value=values):
            with patch.object(stack.pymysql, "connect", return_value=connection):
                with patch.object(stack, "query", return_value=[("DeepSeekDoc",)]) as query:
                    with self.assertRaisesRegex(RuntimeError, "already exists"):
                        stack.initialize()
                    self.assertEqual(query.call_count, 1)
                    self.assertNotIn("CREATE", query.call_args.args[1])

    def test_missing_credentials_fail_before_database_connection(self):
        with patch.object(stack.pymysql, "connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "Fill DB_USERNAME"):
                stack.database({"DB_USERNAME": "", "DB_PASSWORD": ""})
            connect.assert_not_called()

    def test_invalid_database_identifier_is_rejected(self):
        with patch.object(stack.pymysql, "connect") as connect:
            with self.assertRaisesRegex(RuntimeError, "unsupported"):
                stack.database({"DB_USERNAME": "demo", "DB_PASSWORD": "secret",
                                "DB_NAME": "data;DROP DATABASE data"})
            connect.assert_not_called()

    def test_changed_backup_target_prevents_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "prepared.json").write_text(json.dumps({"targetFingerprint": "wrong"}))
            with patch.object(stack, "RUN", run), patch.object(stack, "ensure_private"):
                with patch.object(stack, "config", return_value={"DB_NAME": "expected"}):
                    with patch.object(stack, "database") as database:
                        with self.assertRaisesRegex(RuntimeError, "target changed"):
                            stack.start()
                        database.assert_not_called()

    def test_backup_password_is_not_in_process_arguments_and_temp_file_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "backups").mkdir()
            values = {"DB_USERNAME": "demo", "DB_PASSWORD": 'secret"with\\symbols', "DB_NAME": "demo"}
            commands = []

            def execute(command, **kwargs):
                commands.append(command)
                self.assertNotIn(values["DB_PASSWORD"], " ".join(command))
                temporary = run / "mysql-client.cnf"
                self.assertTrue(temporary.exists())
                destination = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--result-file=")))
                destination.write_text("-- simulated database backup\n" * 20)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(stack, "RUN", run), patch.object(stack, "protect"):
                with patch.object(stack.subprocess, "run", side_effect=execute):
                    backup = stack.backup(values)
            self.assertTrue(backup.exists())
            self.assertFalse((run / "mysql-client.cnf").exists())
            self.assertEqual(len(commands), 1)

    def test_failed_backup_never_returns_a_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "backups").mkdir()
            with patch.object(stack, "RUN", run), patch.object(stack, "protect"):
                with patch.object(stack.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
                    with self.assertRaisesRegex(RuntimeError, "migration was not attempted"):
                        stack.backup({"DB_USERNAME": "demo", "DB_PASSWORD": "secret", "DB_NAME": "demo"})
            self.assertFalse((run / "mysql-client.cnf").exists())

    def test_stop_refuses_reused_pid_owned_by_another_project(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "preview.json").write_text(json.dumps({"ai": {"pid": 12345}}))
            fake = subprocess.CompletedProcess([], 0, stdout="python.exe other-project/server.py")
            with patch.object(stack, "RUN", run):
                with patch.object(stack.subprocess, "run", return_value=fake) as execute:
                    with self.assertRaisesRegex(RuntimeError, "no longer belongs"):
                        stack.stop()
                    self.assertEqual(execute.call_count, 1)
            self.assertTrue((run / "preview.json").exists())


if __name__ == "__main__":
    unittest.main()
