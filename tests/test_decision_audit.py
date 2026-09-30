import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from state.decision_audit import DecisionAudit, _validate_phase, sanitize_audit_record


class DecisionAuditTests(unittest.TestCase):
    def _pre(self):
        with (Path(__file__).parent / "fixtures/decision/audit-valid.json").open() as fh:
            return json.load(fh)

    def _post(self, correlation):
        profile = self._pre()["profile"]
        profile.update({key: {"key": key, "value": .9, "status": "answered", "confidence": .9, "provider_id": "safe"} for key in ("meaningful_progress", "requirements_satisfied", "another_iteration_useful", "requires_escalation")})
        return {"feature": "demo", "task": "T005", "correlationId": correlation, "eventualResult": {"status": "ok"}, "comparison": {"postProfile": profile, "confidence": {"min": .9, "mean": .9, "perAnswer": [.9] * 13}, "policyReasonCodes": ["post_evaluation_complete"], "authoritativePreDecision": {}, "eventual": {"role": "worker", "result": {"status": "ok"}, "gates": [], "model": None, "usage": {"latencyMs": 1, "inputTokens": None, "outputTokens": None, "cost": None}}, "mismatches": []}, "usage": {"latencyMs": 1, "inputTokens": None, "outputTokens": None, "cost": None}, "model": None}

    def test_stable_pre_and_append_post(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = DecisionAudit(directory)
            one = audit.record_pre(self._pre())
            two = audit.record_pre(self._pre())
            self.assertEqual(one, two)
            audit.record_post(self._post(one))
            records = [json.loads(line) for line in (Path(directory) / ".agent-managed/runtime/decision-audit.jsonl").read_text().splitlines()]
            self.assertEqual([record["phase"] for record in records], ["pre_execution", "pre_execution", "post_execution"])
            self.assertFalse(records[-1]["orphanedPreObservation"])

    def test_secrets_and_forbidden_keys_rejected(self):
        with self.assertRaises(ValueError):
            sanitize_audit_record({"apiKey": "secret"})
        with self.assertRaises(ValueError):
            sanitize_audit_record({"fact": "Bearer abcdefghijklmnopqrstuvwxyz"})

    def test_orphan_post_and_write_failure_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = DecisionAudit(directory)
            audit.record_post({"correlationId": "missing", "eventualResult": {}, "comparison": {}, "usage": {}, "model": None})
            self.assertFalse((Path(directory) / ".agent-managed/runtime/decision-audit.jsonl").exists())
            DecisionAudit(Path(directory) / "not-a-directory").record_post({"correlationId": "x"})

    def test_raw_classes_and_phase_shapes_are_rejected(self):
        valid = self._pre()
        for name in ("payload", "request", "response", "diff", "full-log", "context"):
            with self.assertRaises(ValueError):
                sanitize_audit_record({name: {}})
        with self.assertRaises(ValueError):
            DecisionAudit().record_pre({"feature": "demo", "task": "T005"})
        with self.assertRaises(ValueError):
            _validate_phase({**self._pre(), "task": "free form task"}, "pre_execution")
        with tempfile.TemporaryDirectory() as directory:
            DecisionAudit(directory).record_post({"correlationId": "x" * 20})
        with tempfile.TemporaryDirectory() as directory:
            correlation = DecisionAudit(directory).record_pre(valid)
            DecisionAudit(directory).record_post({"correlationId": correlation, "eventualResult": {}, "comparison": {"matched": True}, "usage": {}, "model": None})

    def test_invalid_fixture_and_enriched_record_shape(self):
        root = Path(__file__).parent / "fixtures/decision"
        with (root / "audit-invalid.json").open() as fh, self.assertRaises(ValueError):
            DecisionAudit().record_pre(json.load(fh))
        with tempfile.TemporaryDirectory() as directory:
            audit = DecisionAudit(directory)
            correlation = audit.record_pre(self._pre())
            audit.record_post(self._post(correlation))
            records = [json.loads(line) for line in (Path(directory) / ".agent-managed/runtime/decision-audit.jsonl").read_text().splitlines()]
            self.assertEqual(set(records[-2]), {"authoritativeDecision", "confidence", "feature", "kind", "mismatch", "phase", "policyRecommendation", "profile", "provider", "schemaVersion", "task", "usage", "correlationId"})
            self.assertFalse(records[-1]["orphanedPreObservation"])
            self.assertLessEqual(len(json.dumps(records[-1], separators=(",", ":")).encode()), 16 * 1024)

    def test_post_confidence_reason_codes_and_usage_are_strict(self):
        import copy

        correlation = "c" * 20
        valid = self._post(correlation)
        invalid = []
        for value in (2, True, {"min": 0, "mean": 0, "perAnswer": []}):
            record = copy.deepcopy(valid)
            record["comparison"]["confidence"] = value
            invalid.append(record)
        for value in ("", "   ", "x" * 2001, "Bearer abcdefghijklmnopqrstuvwxyz"):
            record = copy.deepcopy(valid)
            record["comparison"]["policyReasonCodes"] = [value]
            invalid.append(record)
        for location in (("usage",), ("comparison", "eventual", "usage")):
            for value in ({"latencyMs": -1, "inputTokens": None, "outputTokens": None, "cost": None}, {"latencyMs": True, "inputTokens": None, "outputTokens": None, "cost": None}, {"latencyMs": 1}):
                record = copy.deepcopy(valid)
                target = record
                for key in location[:-1]:
                    target = target[key]
                target[location[-1]] = value
                invalid.append(record)
        for record in invalid:
            with self.assertRaises(ValueError):
                _validate_phase(record, "post_execution")


if __name__ == "__main__":
    unittest.main()
