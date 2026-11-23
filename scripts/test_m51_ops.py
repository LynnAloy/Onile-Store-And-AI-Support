import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_stack as stack


class PaymentDeploymentTests(unittest.TestCase):
    def test_normal_frontend_cannot_be_redirected_to_fault_proxy(self):
        with patch.object(stack,"DEMO",False), patch.object(stack,"JAVA_PORT",8080):
            self.assertEqual(stack.frontend_java_target({}),"http://127.0.0.1:8080")

    def test_demo_without_fault_proof_uses_direct_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stack,"DEMO",True),patch.object(stack,"RUN",Path(directory)),patch.object(stack,"JAVA_PORT",18080):
                self.assertEqual(stack.frontend_java_target({}),"http://127.0.0.1:18080")

    def test_fault_proxy_wrong_target_is_rejected_before_any_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            (run/"m51d-fault-proxy.json").write_text(json.dumps({"marker":"wrong"}))
            with patch.object(stack,"DEMO",True),patch.object(stack,"RUN",run):
                with self.assertRaisesRegex(RuntimeError,"proof"):
                    stack.frontend_java_target({})

    def test_normal_mode_without_explicit_m6_migration_keeps_payments_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stack, "DEMO", False), patch.object(stack, "RUN", Path(directory)):
                self.assertEqual(stack.payment_mode({}), "false")

    def test_stale_migration_proof_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "m51-migration.json").write_text(json.dumps({"passed": True}))
            with patch.object(stack, "DEMO", True), patch.object(stack, "RUN", run):
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    stack.payment_mode({"DB_NAME": "DeepseekDoc_M43_Demo"})

    def test_payment_mode_requires_matching_schema_and_database_fingerprints(self):
        values = {"DB_NAME": "DeepseekDoc_M43_Demo", "DB_USERNAME": "synthetic"}
        proof = {"passed": True, "targetFingerprint": stack.target_fingerprint(values),
                 "databaseStructureSha256": "synthetic-schema",
                 "schemaSha256": hashlib.sha256((stack.ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "m51-migration.json").write_text(json.dumps(proof))
            with patch.object(stack, "DEMO", True), patch.object(stack, "RUN", run), patch.object(stack,"payment_schema_fingerprint",return_value="synthetic-schema"):
                self.assertEqual(stack.payment_mode(values), "true")
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    stack.payment_mode({**values, "DB_USERNAME": "different"})


if __name__ == "__main__":
    unittest.main()
