"""Side-effect-free decision provider runtime and safe fallback chain."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

try:  # Package import (``state.decision_providers``).
    from .decision import (
        AnswerStatus,
        BoundedDecisionContext,
        ChoiceAnswer,
        DecisionKind,
        DecisionRequest,
        DecisionResult,
        DecisionValidationError,
        ProbabilityAnswer,
        ScoreAnswer,
        canonical_json,
    )
except ImportError:  # Script/runtime convention (state on ``sys.path``).
    from decision import (
        AnswerStatus,
        BoundedDecisionContext,
        ChoiceAnswer,
        DecisionKind,
        DecisionRequest,
        DecisionResult,
        DecisionValidationError,
        ProbabilityAnswer,
        ScoreAnswer,
        canonical_json,
    )


class ProviderStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class ProviderFailure(str, Enum):
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"
    ERROR = "error"
    INVALID = "invalid"
    OVERSIZED = "oversized"


class ProviderError(Exception):
    """Bounded provider failure; its category is safe to expose in attempts."""

    def __init__(self, category: ProviderFailure, message: str = "") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class DecisionProviderCapabilities:
    provider_id: str
    supported_kinds: tuple[DecisionKind, ...]
    status: ProviderStatus
    max_request_bytes: int
    reports_usage: bool = False
    reports_model: bool = False


@runtime_checkable
class DecisionProvider(Protocol):
    def capabilities(self) -> DecisionProviderCapabilities: ...
    def evaluate(self, request: DecisionRequest) -> DecisionResult | "ProviderEvaluation": ...


_MAX_PROVIDER_MODEL_CHARS = 255
_MAX_PROVIDER_COUNT = 1_000_000


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        for value in (self.input_tokens, self.output_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_PROVIDER_COUNT:
                raise DecisionValidationError("invalid provider usage")


@dataclass(frozen=True)
class ProviderResultMetadata:
    model: str | None = None
    usage: ProviderUsage | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if self.model is not None and (
            not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > _MAX_PROVIDER_MODEL_CHARS
        ):
            raise DecisionValidationError("invalid provider model")
        if self.usage is not None and not isinstance(self.usage, ProviderUsage):
            raise DecisionValidationError("invalid provider usage")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, int)
            or not 0 <= self.latency_ms <= _MAX_PROVIDER_COUNT
        ):
            raise DecisionValidationError("invalid provider latency")


@dataclass(frozen=True)
class ProviderEvaluation:
    result: DecisionResult
    metadata: ProviderResultMetadata | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.result, DecisionResult):
            raise DecisionValidationError("invalid provider result")
        if self.metadata is not None and not isinstance(self.metadata, ProviderResultMetadata):
            raise DecisionValidationError("invalid provider metadata")


@dataclass(frozen=True)
class ProviderAttempt:
    provider_id: str
    outcome: str
    failure: ProviderFailure | None = None


@dataclass(frozen=True)
class ProviderChainResult:
    result: DecisionResult
    provider_id: str
    attempts: tuple[ProviderAttempt, ...]
    metadata: ProviderResultMetadata | None = None


def _validate_capabilities(capabilities: DecisionProviderCapabilities) -> None:
    if not capabilities.provider_id.strip() or capabilities.max_request_bytes <= 0:
        raise DecisionValidationError("invalid provider capabilities")
    if len(set(capabilities.supported_kinds)) != len(capabilities.supported_kinds):
        raise DecisionValidationError("duplicate provider decision kind")


class DecisionProviderChain:
    def __init__(self, providers: tuple[DecisionProvider, ...] | list[DecisionProvider]):
        self.providers = tuple(providers)
        ids = [provider.capabilities().provider_id for provider in self.providers]
        if len(set(ids)) != len(ids):
            raise DecisionValidationError("duplicate provider IDs")
        if not self.providers or not isinstance(self.providers[-1], DeterministicSafeProvider):
            self.providers += (DeterministicSafeProvider(),)
        ids = [provider.capabilities().provider_id for provider in self.providers]
        if len(set(ids)) != len(ids):
            raise DecisionValidationError("duplicate provider IDs")

    def evaluate(self, request: DecisionRequest) -> ProviderChainResult:
        request.validate()
        attempts: list[ProviderAttempt] = []
        size = len(canonical_json(request).encode("utf-8"))
        for provider in self.providers:
            caps = provider.capabilities()
            _validate_capabilities(caps)
            if size > caps.max_request_bytes:
                attempts.append(ProviderAttempt(caps.provider_id, "failure", ProviderFailure.OVERSIZED))
                continue
            if caps.status is not ProviderStatus.AVAILABLE:
                attempts.append(ProviderAttempt(caps.provider_id, "failure", ProviderFailure(caps.status.value)))
                continue
            if any(q.kind not in caps.supported_kinds for q in request.schema.questions):
                attempts.append(ProviderAttempt(caps.provider_id, "failure", ProviderFailure.UNSUPPORTED))
                continue
            try:
                evaluation = provider.evaluate(request)
                if isinstance(evaluation, ProviderEvaluation):
                    result, metadata = evaluation.result, evaluation.metadata
                elif isinstance(evaluation, DecisionResult):
                    result, metadata = evaluation, None
                else:
                    raise DecisionValidationError("invalid provider result")
                result.validate(request.schema)
            except ProviderError as error:
                attempts.append(ProviderAttempt(caps.provider_id, "failure", error.category))
                continue
            except (AttributeError, DecisionValidationError, TypeError, ValueError):
                attempts.append(ProviderAttempt(caps.provider_id, "failure", ProviderFailure.INVALID))
                continue
            attempts.append(ProviderAttempt(caps.provider_id, "success"))
            return ProviderChainResult(result, caps.provider_id, tuple(attempts), metadata)
        raise RuntimeError("provider chain has no usable terminal provider")


class DeterministicSafeProvider:
    def capabilities(self) -> DecisionProviderCapabilities:
        return DecisionProviderCapabilities(
            "deterministic-safe", tuple(DecisionKind), ProviderStatus.AVAILABLE, 16 * 1024
        )

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        facts = {fact.key: fact.value for fact in request.context.facts}
        answers = []
        known = {"task_type", "complexity", "risk", "architectural_impact"}
        for question in request.schema.questions:
            value = facts.get(question.key) if question.key in known else None
            if question.kind is DecisionKind.CHOICE:
                value = value if isinstance(value, str) and value in question.options else None
                answers.append(ChoiceAnswer(question.key, value, AnswerStatus.ANSWERED if value is not None else AnswerStatus.UNKNOWN, 1.0 if value is not None else 0.0, "deterministic-safe"))
            elif question.kind is DecisionKind.SCORE:
                value = value if isinstance(value, int) and not isinstance(value, bool) and value in question.scale else None
                answers.append(ScoreAnswer(question.key, value, AnswerStatus.ANSWERED if value is not None else AnswerStatus.UNKNOWN, 1.0 if value is not None else 0.0, "deterministic-safe"))
            else:
                answers.append(ProbabilityAnswer(question.key, None, AnswerStatus.UNKNOWN, 0.0, "deterministic-safe"))
        return DecisionResult(tuple(answers), request.schema.version)


class MockDecisionProvider:
    def __init__(self, outcomes: list[DecisionResult | ProviderError | Exception], provider_id: str = "mock") -> None:
        self._outcomes = list(outcomes)
        self.provider_id = provider_id

    def capabilities(self) -> DecisionProviderCapabilities:
        return DecisionProviderCapabilities(self.provider_id, tuple(DecisionKind), ProviderStatus.AVAILABLE, 16 * 1024)

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        if not self._outcomes:
            raise ProviderError(ProviderFailure.UNAVAILABLE)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            if isinstance(outcome, ProviderError):
                raise outcome
            raise ProviderError(ProviderFailure.ERROR) from outcome
        return outcome
