"""Routing recovers gaps without crossing providers, capabilities or role families."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from importlib.machinery import SourceFileLoader

from state import routing, catalog

ROOT = Path(__file__).resolve().parents[1]
kit = SourceFileLoader("kit_recovery", str(ROOT / "bin/agent-kit")).load_module()


class RoutingRecoveryTest(unittest.TestCase):
    def model(self, identifier, rate, *, available=True, classes=None):
        return {"id": identifier, "provider": "copilot", "classes": classes or ["strong-coding"],
                "capabilities": ["coding", "toolcall"], "available": available, "costUnknown": False,
                "inputCostPer1MTokens": rate, "outputCostPer1MTokens": rate,
                "supportsTools": True, "codingCapability": "high", "toolCapability": "high", "reviewCapability": "high"}

    def mapping(self, family="modelClasses", target="cost-efficient-coding", source="strong-coding"):
        return {family: {target: {"candidates": []}, source: {"candidates": [
            {"model": "github-copilot/expensive", "provider": "copilot", "agent": "worker"},
            {"model": "github-copilot/cheap", "provider": "copilot", "agent": "worker"},
        ]}}}

    def resolve(self, mapping, models, family, target, **kwargs):
        lock = {"harnesses": {"opencode": {"models": models}}}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            agents = root / ".opencode/agents"
            agents.mkdir(parents=True)
            for name in ("worker", "reviewer", "qa"):
                (agents / f"{name}.md").write_text("role adapter")
            with patch.object(routing, "consumer_root", return_value=root), patch.object(routing, "load_harness_mapping", return_value=mapping), patch.object(catalog, "load_catalog", return_value=lock), patch.object(routing, "metric_history", return_value={}):
                return routing.resolve_mapping_class("opencode", family, target, provider="copilot", **kwargs)

    def test_empty_class_recovers_cheapest_available_same_provider(self):
        mapping = self.mapping()
        models = [self.model("github-copilot/expensive", 5), self.model("github-copilot/cheap", 1)]
        selected, fallback = self.resolve(mapping, models, "modelClasses", "cost-efficient-coding")
        self.assertEqual("github-copilot/cheap", selected["model"])
        self.assertEqual("catalog-recovery", selected["selectionBasis"])
        self.assertTrue(fallback)
        selected, _ = self.resolve(mapping, models, "modelClasses", "cost-efficient-coding", excluded_models={"github-copilot/cheap"})
        self.assertEqual("github-copilot/expensive", selected["model"])

    def test_review_and_qa_recover_only_from_their_own_family(self):
        for family, target, source, agent in (("reviewClasses", "independent-reviewer", "specialist-review", "reviewer"), ("qaClasses", "qa-basic", "qa-adversarial", "qa")):
            mapping = self.mapping(family, target, source)
            for option in mapping[family][source]["candidates"]:
                option["agent"] = agent
            models = [self.model("github-copilot/cheap", 1)]
            selected, _ = self.resolve(mapping, models, family, target)
            self.assertEqual(agent, selected["agent"])

    def test_recovery_rejects_unavailable_excluded_or_insufficient_models(self):
        mapping = self.mapping()
        for models, excluded, target in (([self.model("github-copilot/cheap", 1, available=False)], set(), "cost-efficient-coding"),
                                 ([self.model("github-copilot/cheap", 1)], {"github-copilot/cheap"}, "cost-efficient-coding"),
                                 ([self.model("github-copilot/cheap", 1, classes=["cost-efficient-coding"])], set(), "strongest-appropriate"),
                                 ([{**self.model("github-copilot/cheap", 1), "provider": "openai"}], set(), "cost-efficient-coding"),
                                 ([{**self.model("github-copilot/cheap", 1), "supportsTools": False}], set(), "cost-efficient-coding")):
            with self.subTest(models=models, excluded=excluded), self.assertRaises(ValueError):
                self.resolve(mapping, models, "modelClasses", target, excluded_models=excluded)

    def test_generation_populates_lower_floors_from_stronger_discovered_models(self):
        mapping, roles = kit.opencode_extra_candidates({"modelClasses": {"cost-efficient-coding": {"candidates": []}}},
                                                     [self.model("github-copilot/gpt-6-sol", 1)])
        self.assertTrue(mapping["modelClasses"]["cost-efficient-coding"]["candidates"])
        self.assertTrue(any(role[0] == "developer-low-copilot" for role in roles))


if __name__ == "__main__":
    unittest.main()
