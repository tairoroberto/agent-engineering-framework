from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "state"))
from model_router import ModelDescriptor, ModelRouter, NoCapableModel, compress_tool_output, escalation_allowed


def model(name: str, *, provider: str = "openai", tier: str = "ECONOMY", coding: str = "high", review: str = "high", reasoning: str = "low", tools: bool = True, context: int | None = 128_000, price: tuple[float, float] | None = None) -> ModelDescriptor:
    return ModelDescriptor(
        provider=provider, model_id=name, cost_tier=tier, coding_capability=coding,
        review_capability=review, reasoning_capability=reasoning, tool_capability="high" if tools else "unknown",
        supports_tools=tools, supports_reasoning=reasoning != "unknown", context_window=context,
        input_cost_per_1m_tokens=price[0] if price else None,
        output_cost_per_1m_tokens=price[1] if price else None,
    )


class ModelRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.models = (
            model("cheap-small", coding="medium", review="medium", price=(1, 2)),
            model("cheap-medium", price=(2, 3)),
            model("expensive-large", tier="PREMIUM", reasoning="high", price=(20, 30)),
        )

    def test_workers_select_cheapest_capable_model(self) -> None:
        router = ModelRouter(self.models)
        for role in ("developer", "qa", "reviewer"):
            self.assertEqual("cheap-small", router.route(role, "openai").selected.model_id)
            self.assertEqual("COST_FIRST", router.route(role, "openai").strategy)

    def test_orchestrator_prefers_reasoning_over_cheapest_price(self) -> None:
        decision = ModelRouter(self.models).route("orchestrator", "openai")
        self.assertEqual("expensive-large", decision.selected.model_id)
        self.assertEqual("CAPABILITY_FIRST", decision.strategy)

    def test_capability_and_context_are_constraints(self) -> None:
        unsupported = model("no-tools", tools=False, price=(0.1, 0.1))
        short = model("short-context", context=100, price=(0.2, 0.2))
        router = ModelRouter((unsupported, short, self.models[0]))
        self.assertEqual("cheap-small", router.route("developer", "openai", context_required=1_000).selected.model_id)

    def test_named_provider_never_crosses_boundary(self) -> None:
        router = ModelRouter((model("only-other", provider="copilot"),))
        with self.assertRaises(NoCapableModel):
            router.route("developer", "openai")

    def test_known_pricing_uses_expected_execution_cost(self) -> None:
        low_input_high_output = model("output-heavy", price=(1, 100))
        balanced = model("balanced", price=(4, 4))
        selected = ModelRouter((low_input_high_output, balanced)).route(
            "developer", "openai", estimated_input_tokens=100, estimated_output_tokens=10_000,
        )
        self.assertEqual("balanced", selected.selected.model_id)

    def test_unknown_pricing_uses_cost_tier_and_unknown_models_work(self) -> None:
        unknown = model("unknown-model-2027", tier="ECONOMY")
        premium = model("new-premium", tier="PREMIUM")
        self.assertEqual("unknown-model-2027", ModelRouter((premium, unknown)).route("developer", "openai").selected.model_id)

    def test_openai_named_fixture_has_no_name_policy(self) -> None:
        fixtures = (
            model("Astra", tier="PREMIUM", reasoning="high", price=(20, 20)),
            model("Sol", tier="PREMIUM", reasoning="high", price=(15, 15)),
            model("Terra", tier="ECONOMY", price=(1, 1)),
            model("Lua", tier="ECONOMY", price=(2, 2)),
            model("5.5", tier="STANDARD", reasoning="high", price=(5, 5)),
        )
        router = ModelRouter(fixtures)
        self.assertEqual("Terra", router.route("developer", "openai").selected.model_id)
        self.assertEqual("Terra", router.route("qa", "openai").selected.model_id)
        self.assertEqual("Terra", router.route("reviewer", "openai").selected.model_id)
        self.assertEqual("5.5", router.route("orchestrator", "openai").selected.model_id)

    def test_escalation_requires_evidence_and_limits_loops(self) -> None:
        self.assertFalse(escalation_allowed("important_task", same_model_attempts=9, tier_escalations=0))
        self.assertFalse(escalation_allowed("capability_missing", same_model_attempts=0, tier_escalations=0))
        self.assertTrue(escalation_allowed("capability_missing", same_model_attempts=1, tier_escalations=0))
        self.assertFalse(escalation_allowed("capability_missing", same_model_attempts=1, tier_escalations=2))

    def test_large_tool_output_is_compressed(self) -> None:
        output = "noise\n" * 2_000 + "ERROR: expected behavior\n" + "tail\n" * 20
        compact = compress_tool_output(output, limit=400)
        self.assertLessEqual(len(compact), 460)
        self.assertIn("ERROR: expected behavior", compact)
        self.assertIn("compressed", compact)


if __name__ == "__main__":
    unittest.main()
