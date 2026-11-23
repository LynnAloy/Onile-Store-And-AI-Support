import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_stack as stack


class CommerceDeploymentTests(unittest.TestCase):
    def proof(self, values):
        return {"passed": True, "targetFingerprint": stack.target_fingerprint(values),
                "schemaSha256": hashlib.sha256((stack.ROOT / "docs/sql/M6-commerce.sql").read_bytes()).hexdigest(),
                "paymentSchemaSha256": hashlib.sha256((stack.ROOT / "docs/sql/M5.1-A.proposed.sql").read_bytes()).hexdigest(),
                "paymentStructureSha256": "payment-structure", "commerceStructureSha256": "commerce-structure"}

    def test_explicit_verified_normal_deployment_enables_both_engines(self):
        values = {"DB_NAME": "synthetic", "DB_USERNAME": "test"}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "m6-migration.json").write_text(json.dumps(self.proof(values)))
            with patch.object(stack, "DEMO", False), patch.object(stack, "RUN", run), \
                    patch.object(stack, "payment_schema_fingerprint", return_value="payment-structure"), \
                    patch.object(stack, "commerce_schema_fingerprint", return_value="commerce-structure"):
                self.assertEqual(stack.payment_mode(values), "true")
                self.assertEqual(stack.commerce_mode(values), "true")

    def test_wrong_target_rejected_before_connecting_to_database(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "m6-migration.json").write_text(json.dumps(self.proof({"DB_NAME": "owned"})))
            with patch.object(stack, "RUN", run), patch.object(stack, "database") as database:
                with self.assertRaisesRegex(RuntimeError, "drifted"):
                    stack.payment_mode({"DB_NAME": "unrelated"})
                database.assert_not_called()

    def test_changed_schema_never_certified_by_matching_target_alone(self):
        values = {"DB_NAME": "synthetic"}
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "m6-migration.json").write_text(json.dumps(self.proof(values)))
            with patch.object(stack, "RUN", run), \
                    patch.object(stack, "payment_schema_fingerprint", return_value="payment-structure"), \
                    patch.object(stack, "commerce_schema_fingerprint", return_value="modified"):
                with self.assertRaisesRegex(RuntimeError, "structure drifted"):
                    stack.commerce_mode(values)
