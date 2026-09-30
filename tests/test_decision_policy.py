import sys
import json
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from state.decision import *  # noqa: F403,F401
from state.decision_policy import *  # noqa: F403,F401


def profile(**overrides):
    c = ChoiceAnswer("task", "bug", AnswerStatus.ANSWERED, 1, "safe")
    s = ScoreAnswer("score", 1, AnswerStatus.ANSWERED, 1, "safe")
    def p(key, value=.1, confidence=1):
        return ProbabilityAnswer(key, value, AnswerStatus.ANSWERED, confidence, "safe")
    values = dict(requires_reasoning=p("reasoning"), requires_review=p("review"), requires_qa=p("qa"), requirements_clear=p("clear"), security_sensitive=p("security"))
    values.update(overrides)
    return TaskDecisionProfile(c, s, s, s, **values)


class PolicyTest(unittest.TestCase):
    def test_golden_policy_matrix(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/decision/policy-golden.json").read_text())
        for case in fixture["cases"]:
            values = {}
            for key in ("reasoning", "review", "qa", "escalation"):
                if key in case["profile"]:
                    values[f"requires_{'escalation' if key == 'escalation' else key}"] = ProbabilityAnswer(
                        key, case["profile"][key], AnswerStatus.ANSWERED,
                        case["profile"].get(f"{key}_confidence", 1), "safe")
            result = DecisionPolicy().evaluate(profile(**values), case["facts"])
            expected = case["expect"]
            self.assertEqual(result.execution_tier.value, expected["tier"], case["name"])
            self.assertEqual(result.model_class_floor, expected["class"], case["name"])
            self.assertEqual((result.invoke_orchestrator, result.require_review, result.require_qa, result.stop_or_escalate),
                             (expected["invoke"], expected["review"], expected["qa"], expected["stop"]), case["name"])
            self.assertEqual(result.reason_codes, tuple(expected["reasons"]), case["name"])

    def test_exact_mapping(self):
        self.assertEqual([execution_class(t) for t in ExecutionTier], list(MODEL_CLASS_ORDER))

    def test_high_risk_floor_cannot_be_lowered(self):
        result = evaluate(profile(), PolicyFacts(risk="CRITICAL"))
        self.assertEqual(result.execution_tier, ExecutionTier.REASONING)
        self.assertEqual(result.model_class_floor, "strong-coding")

    def test_low_confidence_escalates(self):
        result = evaluate(profile(requires_reasoning=ProbabilityAnswer("reasoning", .0, AnswerStatus.ANSWERED, .2, "safe")), PolicyFacts())
        self.assertTrue(result.invoke_orchestrator)
        self.assertTrue(result.stop_or_escalate)

    def test_required_profile_uncertainty_is_conservative(self):
        unknown_review = evaluate(profile(
            requires_review=ProbabilityAnswer("review", None, AnswerStatus.UNKNOWN, .9, "safe")), PolicyFacts())
        self.assertEqual(unknown_review.execution_tier, ExecutionTier.BALANCED)
        self.assertTrue(unknown_review.require_review)
        self.assertFalse(unknown_review.require_qa)
        self.assertTrue(unknown_review.stop_or_escalate)

        unsupported_security = evaluate(profile(
            security_sensitive=ProbabilityAnswer("security", None, AnswerStatus.UNSUPPORTED, .9, "safe")), PolicyFacts())
        self.assertEqual(unsupported_security.execution_tier, ExecutionTier.BALANCED)
        self.assertTrue(unsupported_security.stop_or_escalate)

    def test_low_confidence_required_fields_raise_floor_and_matching_gate(self):
        low_qa = evaluate(profile(
            requires_qa=ProbabilityAnswer("qa", .1, AnswerStatus.ANSWERED, .69, "safe")), PolicyFacts())
        self.assertEqual(low_qa.execution_tier, ExecutionTier.BALANCED)
        self.assertTrue(low_qa.require_qa)
        self.assertTrue(low_qa.stop_or_escalate)

        low_requirements = evaluate(profile(
            requirements_clear=ProbabilityAnswer("clear", .1, AnswerStatus.ANSWERED, .69, "safe")), PolicyFacts())
        self.assertEqual(low_requirements.execution_tier, ExecutionTier.BALANCED)
        self.assertTrue(low_requirements.stop_or_escalate)

    def test_threshold_validation_and_immutability(self):
        with self.assertRaises(PolicyValidationError): PolicyConfig(minimum_confidence=2)
        result = evaluate(profile(), {})
        with self.assertRaises(Exception): result.reason_codes += ("x",)


if __name__ == "__main__": unittest.main()
