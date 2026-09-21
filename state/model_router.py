"""Provider- and harness-agnostic model routing.

This module owns policy.  Harness adapters only say how a selected model is
invoked; they must not decide which role deserves which model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import Any, Iterable


class CostTier(IntEnum):
    ECONOMY = 0
    STANDARD = 1
    PREMIUM = 2


CAPABILITY_LEVELS = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
ROLE_REQUIREMENTS = {
    "orchestrator": ("reasoning", "tools"),
    "planner": ("coding",),
    "developer": ("coding", "tools"),
    "reviewer": ("review",),
    "qa": ("tools",),
    "explorer": ("tools",),
    "researcher": ("tools",),
    "verifier": ("tools",),
    "mechanical": ("tools",),
}
ROLE_BUDGETS = {
    "orchestrator": {"context": "HIGH", "output": "MEDIUM", "reasoning": "HIGH"},
    "developer": {"context": "LOW", "output": "LOW", "reasoning": "LOW"},
    "reviewer": {"context": "LOW", "output": "LOW", "reasoning": "LOW"},
    "qa": {"context": "LOW", "output": "VERY_LOW", "reasoning": "LOW"},
    "explorer": {"context": "LOW", "output": "VERY_LOW", "reasoning": "LOW"},
    "planner": {"context": "LOW", "output": "LOW", "reasoning": "LOW"},
    "researcher": {"context": "LOW", "output": "LOW", "reasoning": "LOW"},
    "verifier": {"context": "LOW", "output": "LOW", "reasoning": "LOW"},
    "mechanical": {"context": "LOW", "output": "VERY_LOW", "reasoning": "LOW"},
}
TOKEN_BUDGETS = {"VERY_LOW": 800, "LOW": 2_000, "MEDIUM": 4_000, "HIGH": 12_000}


@dataclass(frozen=True)
class ModelDescriptor:
    provider: str
    model_id: str
    display_name: str | None = None
    input_cost_per_1m_tokens: float | None = None
    output_cost_per_1m_tokens: float | None = None
    reasoning_cost_per_1m_tokens: float | None = None
    cost_tier: str = "STANDARD"
    reasoning_capability: str = "unknown"
    coding_capability: str = "medium"
    review_capability: str = "medium"
    tool_capability: str = "medium"
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool | None = True
    supports_reasoning: bool | None = None
    supports_structured_output: bool | None = None
    speed_tier: str | None = None
    availability: bool = True
    metadata_source: str = "harness"

    @property
    def estimated_tier_cost(self) -> int:
        try:
            return int(CostTier[self.cost_tier.upper()])
        except KeyError:
            return int(CostTier.STANDARD)

    def expected_cost(self, input_tokens: int, output_tokens: int, reasoning_tokens: int = 0) -> float | None:
        if self.input_cost_per_1m_tokens is None or self.output_cost_per_1m_tokens is None:
            return None
        reasoning_rate = self.reasoning_cost_per_1m_tokens or 0.0
        return ((input_tokens * self.input_cost_per_1m_tokens) + (output_tokens * self.output_cost_per_1m_tokens) + (reasoning_tokens * reasoning_rate)) / 1_000_000

    def supports(self, requirement: str) -> bool:
        if requirement == "tools":
            return self.supports_tools is not False and CAPABILITY_LEVELS.get(self.tool_capability, 0) >= 1
        if requirement == "reasoning":
            # Unknown provider metadata is eligible at the lowest confidence;
            # explicit false remains a hard constraint. Overrides can tighten it.
            return self.supports_reasoning is not False
        if requirement == "coding":
            return CAPABILITY_LEVELS.get(self.coding_capability, 0) >= 1
        if requirement == "review":
            return CAPABILITY_LEVELS.get(self.review_capability, 0) >= 1
        if requirement == "structured_output":
            return self.supports_structured_output is True
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoutingDecision:
    role: str
    provider: str
    selected: ModelDescriptor
    strategy: str
    required_capabilities: tuple[str, ...]
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost: float | None
    rationale: str
    eligible: tuple[ModelDescriptor, ...]
    budgets: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "selectedModel": self.selected.model_id,
            "selectionStrategy": self.strategy,
            "requiredCapabilities": list(self.required_capabilities),
            "costTier": self.selected.cost_tier,
            "estimatedInputTokens": self.estimated_input_tokens,
            "estimatedOutputTokens": self.estimated_output_tokens,
            "estimatedCost": self.estimated_cost,
            "rationale": self.rationale,
            "budgets": self.budgets,
        }


class NoCapableModel(ValueError):
    pass


class ModelRouter:
    """Select the cheapest capable worker and a balanced capable orchestrator."""

    def __init__(self, models: Iterable[ModelDescriptor], *, allow_cross_provider_fallback: bool = False) -> None:
        self.models = tuple(models)
        self.allow_cross_provider_fallback = allow_cross_provider_fallback

    def route(
        self,
        role: str,
        provider: str,
        *,
        required_capabilities: Iterable[str] = (),
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        context_required: int = 0,
    ) -> RoutingDecision:
        role = role.lower()
        requirements = tuple(dict.fromkeys((*ROLE_REQUIREMENTS.get(role, ("tools",)), *required_capabilities)))
        budgets = dict(ROLE_BUDGETS.get(role, ROLE_BUDGETS["mechanical"]))
        estimated_input = estimated_input_tokens or TOKEN_BUDGETS[budgets["context"]]
        estimated_output = estimated_output_tokens or TOKEN_BUDGETS[budgets["output"]]
        pool = [model for model in self.models if model.availability and (provider == "auto" or model.provider == provider)]
        # A named provider is always a hard boundary. Cross-provider fallback is
        # only meaningful when the caller explicitly opted in and requested auto.
        if provider != "auto" and not pool:
            raise NoCapableModel(f"NO_CAPABLE_MODEL: provider {provider} has no available models")
        eligible = [model for model in pool if all(model.supports(item) for item in requirements)
                    and (model.context_window is None or model.context_window >= context_required)]
        if not eligible:
            raise NoCapableModel(
                f"NO_CAPABLE_MODEL: provider {provider} has no model satisfying {','.join(requirements)}"
            )
        if role == "orchestrator":
            # Capability dominates, but equal-capability candidates remain cost-aware.
            selected = max(
                eligible,
                key=lambda model: (
                    CAPABILITY_LEVELS.get(model.reasoning_capability, 0),
                    CAPABILITY_LEVELS.get(model.tool_capability, 0),
                    -self._cost_key(model, estimated_input, estimated_output)[0],
                    -self._cost_key(model, estimated_input, estimated_output)[1],
                ),
            )
            strategy = "CAPABILITY_FIRST"
            rationale = "best available reasoning/tool balance within provider"
        else:
            selected = min(eligible, key=lambda model: self._cost_key(model, estimated_input, estimated_output))
            strategy = "COST_FIRST"
            rationale = "cheapest available model satisfying " + "+".join(requirements)
        return RoutingDecision(
            role, selected.provider, selected, strategy, requirements, estimated_input,
            estimated_output, selected.expected_cost(estimated_input, estimated_output), rationale,
            tuple(eligible), budgets,
        )

    @staticmethod
    def _cost_key(model: ModelDescriptor, input_tokens: int, output_tokens: int) -> tuple[int, float, str]:
        known = model.expected_cost(input_tokens, output_tokens)
        if known is not None:
            return (0, known, model.model_id)
        return (1, float(model.estimated_tier_cost), model.model_id)


VALID_ESCALATION_REASONS = {
    "repeated_implementation_failure", "capability_missing", "context_window_insufficient",
    "tool_support_unavailable", "complexity_reclassified", "ambiguous_architecture",
    "repeated_invalid_patch", "review_convergence_failure",
}


def escalation_allowed(reason: str, *, same_model_attempts: int, tier_escalations: int, explicit_override: bool = False) -> bool:
    """Keep escalation evidence-based and bounded; no importance-based upgrade."""
    if explicit_override:
        return True
    return reason in VALID_ESCALATION_REASONS and same_model_attempts >= 1 and tier_escalations < 2


def compress_tool_output(output: str, *, limit: int = 1600) -> str:
    """Keep failure context useful without forwarding full tool logs."""
    if len(output) <= limit:
        return output
    lines = output.splitlines()
    relevant = [line for line in lines if any(token in line.lower() for token in ("error", "fail", "exception", "assert", "traceback"))]
    selected = (relevant[:8] + lines[-8:])
    compact = "\n".join(dict.fromkeys(selected))
    return compact[:limit] + "\n[tool output compressed; full log available by reference]"
