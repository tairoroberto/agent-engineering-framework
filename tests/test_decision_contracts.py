import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from state.decision import *  # noqa: F403,F401


class DecisionContractsTest(unittest.TestCase):
    def test_fixture_normalization(self):
        schema = DecisionSchema((ChoiceQuestion("task", ("bug", "feature")),))
        root = Path(__file__).parent / "fixtures" / "decision"
        with (root / "contracts-valid.json").open() as fh:
            self.assertIsInstance(DecisionResult.normalize(json.load(fh), schema), DecisionResult)
        with (root / "contracts-invalid.json").open() as fh:
            with self.assertRaises(DecisionValidationError): DecisionResult.normalize(json.load(fh), schema)

    def test_answer_consistency_and_ordered_scale(self):
        with self.assertRaises(DecisionValidationError): ScoreQuestion("x", (2, 1))
        with self.assertRaises(DecisionValidationError): ChoiceAnswer("x", None, AnswerStatus.ANSWERED, .5, "safe")
        with self.assertRaises(DecisionValidationError): ScoreAnswer("x", 1.2, AnswerStatus.ANSWERED, .5, "safe")
        with self.assertRaises(DecisionValidationError): ProbabilityAnswer("x", None, AnswerStatus.UNKNOWN, .5, "openai-model")
    def test_schema_request_and_canonical_round_trip(self):
        schema = DecisionSchema((ChoiceQuestion("task_type", ("bug", "feature")), ScoreQuestion("complexity", (0, 1, 2)), ScoreQuestion("risk", (0, 1, 2)), ScoreQuestion("architectural_impact", (0, 1, 2)), *(ProbabilityQuestion(k) for k in ("requires_reasoning", "requires_review", "requires_qa", "requirements_clear", "security_sensitive"))))
        request = DecisionRequest.from_context(schema, BoundedDecisionContext("ship it", facts=(Fact("urgent", True),)), observation_id="o1")
        encoded = canonical_json(request)
        self.assertEqual(encoded, canonical_json(request))
        self.assertEqual(json.loads(encoded)["schema"]["questions"][0]["options"], ["bug", "feature"])

    def test_fact_credential_patterns_rejected_by_state_checks(self):
        for value in (True, "Bearer abcdefghijklmnopqrstuvwxyz", "sk-test-token"):
            with self.assertRaises(DecisionValidationError):
                Fact("client_secret", value)

    def test_bounds_and_duplicates_rejected(self):
        with self.assertRaises(DecisionValidationError): ChoiceQuestion("x", ("a", "a"))
        with self.assertRaises(DecisionValidationError): DecisionSchema((ProbabilityQuestion("x"), ProbabilityQuestion("x"))).validate()
        with self.assertRaises(DecisionValidationError): BoundedDecisionContext("x", facts=tuple(Fact(str(i), i) for i in range(33))).validate()
        with self.assertRaises(DecisionValidationError): ProbabilityAnswer("x", 1.1, AnswerStatus.ANSWERED, .5, "safe")

    def test_profile_is_vendor_neutral_and_stable(self):
        c = ChoiceAnswer("task_type", "bug", AnswerStatus.ANSWERED, 1, "safe")
        s = ScoreAnswer("score", 2, AnswerStatus.ANSWERED, .8, "safe")
        p = lambda key: ProbabilityAnswer(key, .5, AnswerStatus.ANSWERED, .9, "safe")
        profile = TaskDecisionProfile(c, s, s, s, p("r"), p("v"), p("q"), p("c"), p("s"))
        self.assertEqual(canonical_json(profile), canonical_json(profile))
        self.assertNotIn("model", canonical_json(profile).lower())

    def test_profile_round_trip_and_strict_shape(self):
        c = ChoiceAnswer("task_type", "bug", AnswerStatus.ANSWERED, 1, "safe")
        s = ScoreAnswer("score", 2, AnswerStatus.ANSWERED, .8, "safe")
        p = lambda key: ProbabilityAnswer(key, .5, AnswerStatus.ANSWERED, .9, "safe")
        profile = TaskDecisionProfile(c, s, s, s, p("r"), p("v"), p("q"), p("c"), p("s"))
        self.assertEqual(TaskDecisionProfile.normalize(json.loads(canonical_json(profile))).to_dict(), profile.to_dict())
        malformed = profile.to_dict()
        malformed["task_type"]["value"] = "not-an-option"
        with self.assertRaises(DecisionValidationError):
            DecisionResult.normalize({"answers": [{"key": "task", "value": "nope", "status": "answered", "confidence": 1, "provider_id": "safe"}], "schema_version": 1}, DecisionSchema((ChoiceQuestion("task", ("bug", "feature")),)))
        with self.assertRaises(DecisionValidationError): TaskDecisionProfile.normalize({**profile.to_dict(), "extra": 1})


if __name__ == "__main__": unittest.main()
