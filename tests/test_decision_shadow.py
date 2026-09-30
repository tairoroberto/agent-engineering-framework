import json
import sys
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10+ stdlib; older runners lack TOML support.
    tomllib = None
import unittest
from unittest.mock import patch
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state.decision_shadow import (ContextLimits, DecisionConfig, DecisionConfigError,
                                    build_decision_context, observe_post, observe_pre)
from state.decision import canonical_json
from state.decision_providers import (ProviderChainResult, ProviderResultMetadata, ProviderUsage,
                                      ProviderError, ProviderFailure, DecisionProviderCapabilities,
                                      ProviderStatus, DeterministicSafeProvider)
from state.decision import DecisionKind

AGENT_KIT = Path(__file__).resolve().parents[1] / "bin/agent-kit"
agent_kit = SourceFileLoader("agent_kit", str(AGENT_KIT)).load_module()

FIXTURES = Path(__file__).parent / "fixtures/decision"


class DecisionShadowTests(unittest.TestCase):
    def _jev_fake(self, outcome="success"):
        safe = DeterministicSafeProvider()
        calls = []
        class FakeJev:
            def __init__(self, **kwargs):
                pass
            def capabilities(self):
                return DecisionProviderCapabilities("jev", tuple(DecisionKind), ProviderStatus.AVAILABLE, 16 * 1024, True, True)
            def evaluate(self, request):
                calls.append(request.phase)
                if outcome != "success":
                    raise ProviderError(ProviderFailure(outcome))
                result = safe.evaluate(request)
                return __import__("state.decision_providers", fromlist=["ProviderEvaluation"]).ProviderEvaluation(
                    result, ProviderResultMetadata("jev-model", ProviderUsage(17, 9), 23))
        return FakeJev, calls

    def test_jev_success_pre_and_post_is_single_attempt_and_audits_metadata(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True, "providers": ["jev", "deterministic-safe"]}})
        FakeJev, calls = self._jev_fake()
        with tempfile.TemporaryDirectory() as directory, patch("state.decision_shadow.JevDecisionProvider", FakeJev):
            from state.decision_audit import DecisionAudit
            audit = DecisionAudit(directory, "audit.jsonl")
            route = {"provider": "openai", "class": {"complexity": "LOW"}, "roles": ["developer"], "gates": ["tests"]}
            pre = observe_pre(config, {"id": "T003", "objective": "safe"}, route, audit=audit)
            observe_post(config, {"taskId": "T003", "taskContext": {"objective": "safe"}, "eventualResult": "ok", "model": "developer-model", "usage": {"inputTokens": 101, "outputTokens": 17, "latencyMs": 23, "cost": 4}}, root=directory, correlation_id=pre["correlation_id"], audit=audit)
            records = [json.loads(line) for line in (Path(directory) / "audit.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(calls, ["pre_execution", "post_execution"])
        pre_record, post_record = records
        self.assertEqual(pre_record["provider"]["id"], "jev")
        self.assertEqual(pre_record["provider"]["model"], "jev-model")
        self.assertEqual(pre_record["usage"], {"inputTokens": 17, "outputTokens": 9, "latencyMs": 23, "cost": None})
        self.assertEqual(post_record["model"], "jev-model")
        self.assertEqual(post_record["usage"], {"inputTokens": 17, "outputTokens": 9, "latencyMs": 23, "cost": 4})
        self.assertEqual(post_record["comparison"]["eventual"]["model"], "developer-model")
        self.assertEqual(post_record["comparison"]["eventual"]["usage"], {"inputTokens": 101, "outputTokens": 17, "latencyMs": 23, "cost": 4})
        self.assertEqual(records[0]["authoritativeDecision"]["provider"], "openai")

    def test_jev_failures_fallback_once_and_audit_only_safe_normalized_facts(self):
        for category in ("invalid", "unavailable", "timeout", "error"):
            with self.subTest(category=category):
                config = DecisionConfig.from_manifest({"decision": {"enabled": True, "providers": ["jev", "deterministic-safe"]}})
                FakeJev, calls = self._jev_fake(category)
                with tempfile.TemporaryDirectory() as directory, patch("state.decision_shadow.JevDecisionProvider", FakeJev):
                    from state.decision_audit import DecisionAudit
                    audit = DecisionAudit(directory, "audit.jsonl")
                    result = observe_pre(config, {"id": "T003", "objective": "safe"}, audit=audit)
                    record = json.loads((Path(directory) / "audit.jsonl").read_text())
                self.assertEqual(calls, ["pre_execution"])
                self.assertEqual(result["provider"]["id"], "deterministic-safe")
                text = json.dumps(record)
                for marker in ("Authorization", "SENTINEL_API_KEY", "raw-request", "raw-response", "probabilities", "legend", "remote failure text"):
                    self.assertNotIn(marker, text)
    def test_missing_or_disabled_returns_before_observation(self):
        self.assertIsNone(observe_pre(DecisionConfig(), {"objective": "secret"}))

    def test_config_rejects_active_mode_and_invalid_bounds(self):
        with self.assertRaises(DecisionConfigError):
            DecisionConfig.from_manifest({"decision": {"enabled": True, "mode": "active"}})
        with self.assertRaises(DecisionConfigError):
            DecisionConfig.from_manifest({"decision": {"context": {"max_questions": 13}}})

    def test_jev_config_is_strict_and_validated(self):
        config = DecisionConfig.from_manifest({"decision": {"jev": {"endpoint": "https://example.test/api", "model": "m", "timeout": 1.5}}})
        self.assertEqual((config.jev.endpoint, config.jev.model, config.jev.timeout_seconds), ("https://example.test/api", "m", 1.5))
        for key in ("api_key", "headers", "token", "unknown"):
            with self.subTest(key=key), self.assertRaises(DecisionConfigError):
                DecisionConfig.from_manifest({"decision": {"jev": {key: "secret"}}})

    def test_chain_without_jev_does_not_construct_jev(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True, "providers": ["deterministic-safe"]}})
        with patch("state.decision_shadow.JevDecisionProvider", side_effect=AssertionError("constructed")):
            result = observe_pre(config, {"objective": "safe"})
        self.assertEqual(result["provider"]["id"], "deterministic-safe")

    def test_context_is_bounded_and_excludes_untrusted_fields(self):
        context = build_decision_context(
            {"objective": "x" * 3000, "prompt": "do not persist", "requirements": ["r"]},
            limits=ContextLimits(max_text_chars=10),
        )
        self.assertEqual(len(context.objective), 10)
        self.assertEqual(context.requirements, ("r",))
        self.assertNotIn("prompt", {fact.key for fact in context.facts})

    def test_golden_fixtures_cover_context_security_and_bounds(self):
        data = json.loads((FIXTURES / "shadow-context.json").read_text())
        for case in data["cases"]:
            with self.subTest(case=case["name"]):
                limits = ContextLimits(**case["limits"])
                if case["expected_json"] == "REJECT":
                    with self.assertRaises(DecisionConfigError):
                        build_decision_context(case["task"], limits=limits)
                else:
                    context = build_decision_context(case["task"], limits=limits)
                    self.assertEqual(canonical_json(context), case["expected_json"])
                    self.assertLessEqual(len(canonical_json(context).encode()), limits.max_bytes)

    def test_strict_manifest_validation_golden_fixture(self):
        data = json.loads((FIXTURES / "shadow-config.json").read_text())
        for raw in data["invalid"]:
            with self.subTest(raw=raw):
                with self.assertRaises(DecisionConfigError):
                    DecisionConfig.from_manifest(raw)

    def test_toml_config_fixtures(self):
        text = (FIXTURES / "config-valid.toml").read_text()
        valid = tomllib.loads(text) if tomllib is not None else agent_kit.load_flat_toml(FIXTURES / "config-valid.toml")
        config = DecisionConfig.from_manifest(valid)
        self.assertTrue(config.enabled)
        self.assertEqual(config.providers, ("mock", "deterministic-safe"))
        self.assertEqual(config.audit_path, "tmp/decision-audit.jsonl")
        self.assertEqual((config.jev.endpoint, config.jev.model, config.jev.timeout_seconds),
                         ("https://api.typesafe.ai/v1/systemone", "jev-latest", 10.0))
        self.assertEqual(config.policy.minimum_confidence, 0.8)
        self.assertEqual(config.context.max_bytes, 8192)

        invalid = tomllib.loads((FIXTURES / "config-invalid.toml").read_text()) if tomllib is not None else agent_kit.load_flat_toml(FIXTURES / "config-invalid.toml")
        with self.assertRaises(DecisionConfigError):
            DecisionConfig.from_manifest(invalid)

    def test_templates_and_toml_fixtures_contain_no_credential_like_text(self):
        forbidden = ("api_key", "apikey", "token", "authorization", "header", "secret", "sentinel_api_key")
        files = [Path(__file__).parents[1] / "templates/agent-framework.toml"]
        files.extend(sorted(FIXTURES.glob("config-*.toml")))
        self.assertEqual({path.name for path in files}, {"agent-framework.toml", "config-invalid.toml", "config-valid.toml"})
        for path in files:
            with self.subTest(path=path):
                text = path.read_text().lower()
                self.assertFalse(any(marker in text for marker in forbidden), path)

    def test_toml_jev_config_rejects_credentials_and_unknown_fields(self):
        for key in ("api_key", "token", "headers", "Authorization", "secret"):
            with self.subTest(key=key):
                with self.assertRaises(DecisionConfigError):
                    DecisionConfig.from_manifest({"decision": {"jev": {key: "secret"}}})

    def test_configured_order_fallback_and_policy_loop_facts(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True, "providers": ["mock", "jev", "deterministic-safe"]}})
        with tempfile.TemporaryDirectory() as directory:
            from state.decision_audit import DecisionAudit
            result = observe_pre(config, {"objective": "safe", "requirements": ["r"]},
                                 {"complexity": "HIGH", "risk": "HIGH", "requires_review": True,
                                  "requires_qa": True, "executionPolicy": {"retry_ceiling": 1}},
                                 {"history": [{"retry_count": 1}]},
                                 audit=DecisionAudit(directory))
        self.assertEqual(result["provider"]["id"], "deterministic-safe")
        self.assertEqual(result["policyRecommendation"]["executionTier"], "FRONTIER")

    def test_audit_correlation_pre_post_same_ledger(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True, "audit_path": "tmp/audit.jsonl"}})
        with tempfile.TemporaryDirectory() as directory:
            from state.decision_audit import DecisionAudit
            audit = DecisionAudit(directory, config.audit_path)
            pre = observe_pre(config, {"id": "T001", "feature": "demo", "objective": "safe"}, audit=audit)
            observe_post(config, {"feature": "demo", "task": "T001", "eventualResult": "ok", "comparison": {}, "usage": {}, "model": None},
                         root=directory, correlation_id=pre["correlation_id"], audit=audit)
            lines = Path(directory, config.audit_path).read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["correlationId"], json.loads(lines[1])["correlationId"])
            self.assertFalse(json.loads(lines[1])["orphanedPreObservation"])

    def test_post_audit_uses_provider_metadata_without_mutating_receipt_fields(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True}})
        with tempfile.TemporaryDirectory() as directory:
            class CaptureAudit:
                records = []
                def record_post(self, record):
                    self.records.append(record)
            audit = CaptureAudit()
            context = build_decision_context({"objective": "safe"})
            result, profile_data = __import__("state.decision_shadow", fromlist=["_run"])._run(
                config, context, "post_execution", "T001"
            )
            jev_result = ProviderChainResult(
                result.result, "jev", result.attempts,
                ProviderResultMetadata("jev-test", ProviderUsage(13, 8), 21),
            )
            with patch("state.decision_shadow._run", return_value=(jev_result, profile_data)):
                observe_post(config, {
                    "feature": "demo", "taskId": "T001", "eventualResult": "ok",
                    "comparison": {}, "usage": {"latencyMs": 999, "inputTokens": 1, "outputTokens": 2, "cost": 3},
                    "model": "developer-receipt-model",
                }, root=directory, audit=audit)
            record = audit.records[0]
            self.assertEqual("jev-test", record["model"])
            self.assertEqual({"latencyMs": 21, "inputTokens": 13, "outputTokens": 8, "cost": 3}, record["usage"])
            self.assertEqual("developer-receipt-model", record["comparison"]["eventual"]["model"])
            self.assertEqual({"latencyMs": 999, "inputTokens": 1, "outputTokens": 2, "cost": 3}, record["comparison"]["eventual"]["usage"])

    def test_structured_diagnostic_is_non_sensitive(self):
        config = DecisionConfig.from_manifest({"decision": {"enabled": True}})
        result = observe_pre(config, {"objective": "secret objective"})
        self.assertEqual(result["diagnostic"]["code"], "internal_failure")
        self.assertNotIn("secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
