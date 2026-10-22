"""Pure, conservative policy for normalized decision profiles."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Mapping

try:
    from .decision import TaskDecisionProfile, AnswerStatus
    from .routing import MODEL_CLASS_ORDER
except ImportError:
    from decision import TaskDecisionProfile, AnswerStatus
    from routing import MODEL_CLASS_ORDER


class PolicyValidationError(ValueError):
    pass


class ExecutionTier(str, Enum):
    ECONOMY = "ECONOMY"
    BALANCED = "BALANCED"
    REASONING = "REASONING"
    FRONTIER = "FRONTIER"


@dataclass(frozen=True)
class PolicyConfig:
    minimum_confidence: float = .70
    reasoning_probability: float = .70
    review_probability: float = .60
    qa_probability: float = .60
    escalation_probability: float = .70

    def __post_init__(self) -> None:
        values = (self.minimum_confidence, self.reasoning_probability,
                  self.review_probability, self.qa_probability,
                  self.escalation_probability)
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise PolicyValidationError("policy thresholds must be finite values in 0..1")


@dataclass(frozen=True)
class PolicyFacts:
    complexity: str = "LOW"
    risk: str = "LOW"
    require_review: bool = False
    require_qa: bool = False
    gate_failed: bool = False
    convergence_stop: bool = False


@dataclass(frozen=True)
class PolicyRecommendation:
    execution_tier: ExecutionTier
    model_class_floor: str
    invoke_orchestrator: bool
    require_review: bool
    require_qa: bool
    stop_or_escalate: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class DecisionPolicy:
    """Reusable, side-effect-free decision policy evaluator."""

    config: PolicyConfig = PolicyConfig()

    def evaluate(
        self, profile: TaskDecisionProfile,
        facts: PolicyFacts | Mapping[str, Any] = PolicyFacts(),
    ) -> PolicyRecommendation:
        return evaluate(profile, facts, self.config)


def execution_class(tier: ExecutionTier) -> str:
    try:
        return dict(zip(ExecutionTier, MODEL_CLASS_ORDER))[ExecutionTier(tier)]
    except (KeyError, ValueError) as exc:
        raise PolicyValidationError("invalid execution tier") from exc


def _prob(answer: Any, config: PolicyConfig) -> float | None:
    if answer is None or answer.status is not AnswerStatus.ANSWERED or answer.value is None:
        return None
    return float(answer.value) if answer.confidence >= config.minimum_confidence else None


def _uncertain(answer: Any, config: PolicyConfig) -> bool:
    """Treat missing/unsupported/low-confidence required answers as unsafe."""
    return (answer.status is not AnswerStatus.ANSWERED
            or answer.value is None
            or answer.confidence < config.minimum_confidence)


def evaluate(profile: TaskDecisionProfile, facts: PolicyFacts | Mapping[str, Any], config: PolicyConfig | None = None) -> PolicyRecommendation:
    """Evaluate without I/O, provider/model lookup, mutation, or side effects."""
    if not isinstance(profile, TaskDecisionProfile):
        raise PolicyValidationError("profile must be TaskDecisionProfile")
    config = config or PolicyConfig()
    if isinstance(facts, Mapping):
        facts = PolicyFacts(**{k: facts[k] for k in PolicyFacts.__dataclass_fields__ if k in facts})
    if not isinstance(facts, PolicyFacts):
        raise PolicyValidationError("facts must be PolicyFacts or mapping")
    reasons: list[str] = []
    floor = 0
    risk = str(facts.risk).upper()
    complexity = str(facts.complexity).upper()
    if risk in {"HIGH", "CRITICAL"}: floor = max(floor, 2); reasons.append("deterministic-risk")
    if complexity == "HIGH": floor = max(floor, 2); reasons.append("deterministic-complexity")
    if facts.require_review: floor = max(floor, 1); reasons.append("required-review")
    if facts.require_qa: floor = max(floor, 1); reasons.append("required-qa")
    if facts.require_review and facts.require_qa and risk in {"HIGH", "CRITICAL"}: floor = max(floor, 3); reasons.append("dual-verification")
    if facts.gate_failed: floor = max(floor, 2); reasons.append("gate-failure")
    if facts.convergence_stop: floor = max(floor, 3); reasons.append("convergence-stop")
    required = (
        profile.task_type, profile.complexity, profile.risk,
        profile.architectural_impact, profile.requires_reasoning,
        profile.requires_review, profile.requires_qa,
        profile.requirements_clear, profile.security_sensitive,
    )
    uncertain = any(_uncertain(answer, config) for answer in required)
    if uncertain:
        reasons.append("incomplete-or-low-confidence-profile")
        floor = max(floor, 1)
    elif _prob(profile.requires_reasoning, config) is not None and _prob(profile.requires_reasoning, config) >= config.reasoning_probability:
        floor = max(floor, 2); reasons.append("reasoning-needed")
    review = facts.require_review or (p := _prob(profile.requires_review, config)) is not None and p >= config.review_probability
    qa = facts.require_qa or (p := _prob(profile.requires_qa, config)) is not None and p >= config.qa_probability
    if _uncertain(profile.requires_review, config):
        review = True
    if _uncertain(profile.requires_qa, config):
        qa = True
    escalation = profile.requires_escalation
    escalate = uncertain or facts.gate_failed or facts.convergence_stop or (escalation is not None and (escalation.confidence < config.minimum_confidence or ((_prob(escalation, config) or 0) >= config.escalation_probability)))
    if escalate: reasons.append("orchestrator-escalation")
    tier = ExecutionTier(list(ExecutionTier)[floor])
    return PolicyRecommendation(tier, execution_class(tier), escalate, bool(review), bool(qa), escalate, tuple(dict.fromkeys(reasons)))
