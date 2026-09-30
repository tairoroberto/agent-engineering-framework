import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state.decision import (
    BoundedDecisionContext, ChoiceQuestion, DecisionRequest, DecisionSchema, Fact,
    ProbabilityQuestion, ScoreQuestion,
)
from state.decision_providers import (
    DeterministicSafeProvider, DecisionProviderChain, MockDecisionProvider,
    DecisionProviderCapabilities, ProviderStatus,
    ProviderError, ProviderFailure,
    ProviderEvaluation, ProviderResultMetadata, ProviderUsage,
)


def request():
    return DecisionRequest.from_context(
        DecisionSchema((
            ChoiceQuestion("task_type", ("bug", "feature")),
            ScoreQuestion("complexity", (0, 1, 2)),
            ScoreQuestion("risk", (0, 1, 2)),
            ScoreQuestion("architectural_impact", (0, 1, 2)),
            *(ProbabilityQuestion(key) for key in (
                "requires_reasoning", "requires_review", "requires_qa",
                "requirements_clear", "security_sensitive",
            )),
        )),
        BoundedDecisionContext("objective", facts=(Fact("task_type", "bug"),)),
    )


class ProviderTests(unittest.TestCase):
    def test_metadata_is_immutable_and_validated(self):
        metadata = ProviderResultMetadata("jev-1", ProviderUsage(3, 4), 12)
        with self.assertRaises(FrozenInstanceError):
            metadata.model = "other"
        for value in ("", " " * 256):
            with self.assertRaises(ValueError):
                ProviderResultMetadata(value)
        for value in (-1, True, 1.5, 1_000_001):
            with self.assertRaises(ValueError):
                ProviderUsage(value, 0)
            with self.assertRaises(ValueError):
                ProviderUsage(0, value)
            with self.assertRaises(ValueError):
                ProviderResultMetadata(latency_ms=value)

    def test_success_metadata_propagates_and_legacy_results_remain_compatible(self):
        class MetadataProvider(MockDecisionProvider):
            def evaluate(self, request):
                return ProviderEvaluation(
                    super().evaluate(request),
                    ProviderResultMetadata("jev-1", ProviderUsage(3, 4), 12),
                )

        result = DecisionProviderChain([MetadataProvider([DeterministicSafeProvider().evaluate(request())], "jev")]).evaluate(request())
        self.assertEqual(result.metadata.model, "jev-1")
        legacy = DecisionProviderChain([MockDecisionProvider([DeterministicSafeProvider().evaluate(request())], "legacy")]).evaluate(request())
        self.assertIsNone(legacy.metadata)

    def test_failure_attempts_and_fallback_have_no_metadata(self):
        result = DecisionProviderChain([MockDecisionProvider([ProviderError(ProviderFailure.ERROR)], "primary")]).evaluate(request())
        self.assertIsNone(result.metadata)
        self.assertEqual(result.attempts[0].failure, ProviderFailure.ERROR)

    def test_request_uses_canonical_pre_execution_schema(self):
        self.assertEqual(
            {question.key for question in request().schema.questions},
            {
                "task_type", "complexity", "risk", "architectural_impact",
                "requires_reasoning", "requires_review", "requires_qa",
                "requirements_clear", "security_sensitive",
            },
        )

    def test_package_and_script_import_contracts(self):
        root = Path(__file__).parents[1]
        self.assertEqual(subprocess.run(
            [sys.executable, "-c", "import state.decision_providers"], cwd=root,
            check=True, capture_output=True, text=True).returncode, 0)
        self.assertEqual(subprocess.run(
            [sys.executable, "-c", "import decision_providers"], cwd=root / "state",
            check=True, capture_output=True, text=True).returncode, 0)

    def test_ordered_one_shot_success(self):
        first = MockDecisionProvider([ProviderError(ProviderFailure.TIMEOUT)], "first")
        second = MockDecisionProvider([DeterministicSafeProvider().evaluate(request())], "second")
        result = DecisionProviderChain([first, second]).evaluate(request())
        self.assertEqual(result.provider_id, "second")
        self.assertEqual([a.provider_id for a in result.attempts], ["first", "second"])

    def test_all_normalized_failures_fall_back(self):
        for failure in ProviderFailure:
            with self.subTest(failure=failure):
                provider = MockDecisionProvider([ProviderError(failure)], "primary")
                result = DecisionProviderChain([provider]).evaluate(request())
                self.assertEqual(result.provider_id, "deterministic-safe")
                self.assertEqual(result.attempts[0].failure, failure)

    def test_oversized_and_capability_mismatch_fall_back(self):
        class Limited(MockDecisionProvider):
            def capabilities(self):
                caps = super().capabilities()
                return DecisionProviderCapabilities(caps.provider_id, caps.supported_kinds, caps.status, 1)
        result = DecisionProviderChain([Limited([], "large")]).evaluate(request())
        self.assertEqual(result.attempts[0].failure, ProviderFailure.OVERSIZED)

        class Mismatch(MockDecisionProvider):
            def capabilities(self):
                caps = super().capabilities()
                return DecisionProviderCapabilities(caps.provider_id, (), caps.status, caps.max_request_bytes)
        result = DecisionProviderChain([Mismatch([], "mismatch")]).evaluate(request())
        self.assertEqual(result.attempts[0].failure, ProviderFailure.UNSUPPORTED)

    def test_duplicate_ids_and_invalid_capabilities_rejected(self):
        with self.assertRaises(ValueError):
            DecisionProviderChain([MockDecisionProvider([], "same"), MockDecisionProvider([], "same")])
        class Invalid(MockDecisionProvider):
            def capabilities(self):
                return DecisionProviderCapabilities("", (), ProviderStatus.AVAILABLE, 0)
        with self.assertRaises(ValueError):
            DecisionProviderChain([Invalid([], "ignored")]).evaluate(request())

    def test_invalid_results_fall_back(self):
        invalid = object()
        result = DecisionProviderChain([MockDecisionProvider([invalid], "bad")]).evaluate(request())
        self.assertEqual(result.attempts[0].failure, ProviderFailure.INVALID)

    def test_terminal_fallback_is_mandatory(self):
        result = DecisionProviderChain([]).evaluate(request())
        self.assertEqual(result.provider_id, "deterministic-safe")
        self.assertIsNone(result.attempts[-1].failure)

    def test_chain_falls_through_once_and_records_categories(self):
        first = MockDecisionProvider([ProviderError(ProviderFailure.TIMEOUT)], "first")
        result = DecisionProviderChain([first]).evaluate(request())
        self.assertEqual(result.provider_id, "deterministic-safe")
        self.assertEqual([a.failure for a in result.attempts], [ProviderFailure.TIMEOUT, None])

    def test_safe_provider_preserves_known_and_unknown_semantics(self):
        result = DeterministicSafeProvider().evaluate(request())
        self.assertEqual(result.answers[0].value, "bug")
        self.assertIsNone(result.answers[1].value)
        self.assertEqual(result.answers[1].status.value, "unknown")

    def test_mock_outcomes_are_consumed_once(self):
        provider = MockDecisionProvider([ProviderError(ProviderFailure.UNAVAILABLE)], "mocked")
        chain = DecisionProviderChain([provider])
        chain.evaluate(request())
        self.assertEqual(len(provider._outcomes), 0)


if __name__ == "__main__":
    unittest.main()
