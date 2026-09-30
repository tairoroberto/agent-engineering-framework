"""Vendor-neutral, bounded contracts for semantic task decisions."""
from __future__ import annotations

import json
import math
import re
import importlib.util
from pathlib import Path
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Union


class DecisionValidationError(ValueError):
    """Raised when a decision contract is malformed or exceeds its bounds."""


_FORBIDDEN = re.compile(r"prompt|transcript|conversation|thread|session|reasoning|secret|credential|api.?key|access.?token|refresh.?token|auth.?token", re.I)
_STATE_SPEC = importlib.util.spec_from_file_location("agent_state_runtime_decision", Path(__file__).with_name("state.py"))
_STATE_RUNTIME = importlib.util.module_from_spec(_STATE_SPEC) if _STATE_SPEC and _STATE_SPEC.loader else None
if _STATE_RUNTIME is not None:
    _STATE_SPEC.loader.exec_module(_STATE_RUNTIME)


def _safe_fact_text(value: str, name: str) -> str:
    if _FORBIDDEN.search(value) or (_STATE_RUNTIME is not None and _STATE_RUNTIME.contains_credential(value)):
        raise DecisionValidationError(f"forbidden decision field: {name}")
    return value


class DecisionKind(str, Enum):
    CHOICE = "choice"
    SCORE = "score"
    PROBABILITY = "probability"


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionValidationError(f"{name} must be a non-empty string")
    return value


def _prob(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise DecisionValidationError(f"{name} must be finite and in 0..1")
    return float(value)


@dataclass(frozen=True)
class ChoiceQuestion:
    key: str
    options: tuple[str, ...]
    kind: DecisionKind = DecisionKind.CHOICE

    def __post_init__(self) -> None:
        _text(self.key, "key")
        if not self.options or any(not isinstance(x, str) or not x for x in self.options) or len(set(self.options)) != len(self.options):
            raise DecisionValidationError("choice options must be non-empty and unique")


@dataclass(frozen=True)
class ScoreQuestion:
    key: str
    scale: tuple[int, ...]
    kind: DecisionKind = DecisionKind.SCORE

    def __post_init__(self) -> None:
        _text(self.key, "key")
        if not self.scale or len(set(self.scale)) != len(self.scale) or any(isinstance(x, bool) or not isinstance(x, int) for x in self.scale):
            raise DecisionValidationError("score scale must be non-empty and contain unique integers")
        if tuple(sorted(self.scale)) != self.scale:
            raise DecisionValidationError("score scale must be ordered")


@dataclass(frozen=True)
class ProbabilityQuestion:
    key: str
    kind: DecisionKind = DecisionKind.PROBABILITY

    def __post_init__(self) -> None:
        _text(self.key, "key")


Question = Union[ChoiceQuestion, ScoreQuestion, ProbabilityQuestion]


@dataclass(frozen=True)
class Fact:
    key: str
    value: str | int | float | bool

    def __post_init__(self) -> None:
        _text(self.key, "fact key")
        _safe_fact_text(self.key, "fact key")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise DecisionValidationError("fact number must be finite")
        if isinstance(self.value, str):
            _safe_fact_text(self.value, "fact value")


@dataclass(frozen=True)
class BoundedDecisionContext:
    objective: str
    requirements: tuple[str, ...] = ()
    facts: tuple[Fact, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip() or len(self.objective) > 2000:
            raise DecisionValidationError("objective must be non-empty and at most 2000 characters")
        if len(self.requirements) > 32 or any(not isinstance(x, str) or not x.strip() or len(x) > 2000 for x in self.requirements):
            raise DecisionValidationError("requirements exceed bounds")
        if len(self.facts) > 32 or any(len(f.key) > 2000 or (isinstance(f.value, str) and len(f.value) > 2000) for f in self.facts):
            raise DecisionValidationError("context exceeds metadata bounds")


@dataclass(frozen=True)
class DecisionSchema:
    questions: tuple[Question, ...]
    version: int = 1

    def validate(self) -> None:
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise DecisionValidationError("schema version must be a positive integer")
        if not self.questions or len(self.questions) > 13:
            raise DecisionValidationError("schema must contain 1..13 questions")
        keys = [q.key for q in self.questions]
        if len(set(keys)) != len(keys):
            raise DecisionValidationError("duplicate question key")


@dataclass(frozen=True)
class DecisionRequest:
    schema_version: int
    observation_id: str
    phase: str
    schema: DecisionSchema
    context: BoundedDecisionContext
    metadata: tuple[Fact, ...] = ()

    def validate(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise DecisionValidationError("request schema version must be an integer")
        _text(self.observation_id, "observation_id")
        if self.phase not in {"pre_execution", "post_execution"}:
            raise DecisionValidationError("invalid phase")
        self.schema.validate()
        expected = {
            "pre_execution": {"task_type", "complexity", "risk", "architectural_impact", "requires_reasoning", "requires_review", "requires_qa", "requirements_clear", "security_sensitive"},
            "post_execution": {"task_type", "complexity", "risk", "architectural_impact", "requires_reasoning", "requires_review", "requires_qa", "requirements_clear", "security_sensitive", "meaningful_progress", "requirements_satisfied", "another_iteration_useful", "requires_escalation"},
        }[self.phase]
        if {q.key for q in self.schema.questions} != expected:
            raise DecisionValidationError("schema keys do not match phase contract")
        if self.schema_version != self.schema.version:
            raise DecisionValidationError("request schema mismatch")
        self.context.validate()
        if len(self.metadata) > 32:
            raise DecisionValidationError("metadata exceeds 32 facts")
        if len(canonical_json(self).encode("utf-8")) > 16 * 1024:
            raise DecisionValidationError("request exceeds 16KiB")

    @classmethod
    def from_context(cls, schema: DecisionSchema, context: BoundedDecisionContext, metadata: tuple[Fact, ...] = (), observation_id: str = "observation", phase: str = "pre_execution") -> "DecisionRequest":
        result = cls(schema.version, observation_id, phase, schema, context, metadata)
        result.validate()
        return result


@dataclass(frozen=True)
class ChoiceAnswer:
    key: str
    value: str | None
    status: AnswerStatus
    confidence: float
    provider_id: str

    def __post_init__(self) -> None:
        _answer_common(self.key, self.value, self.status, self.confidence, self.provider_id)
        if self.value is not None and not isinstance(self.value, str):
            raise DecisionValidationError("choice value must be a string")


@dataclass(frozen=True)
class ScoreAnswer:
    key: str
    value: int | None
    status: AnswerStatus
    confidence: float
    provider_id: str

    def __post_init__(self) -> None:
        _answer_common(self.key, self.value, self.status, self.confidence, self.provider_id)
        if self.value is not None and (isinstance(self.value, bool) or not isinstance(self.value, int)):
            raise DecisionValidationError("score value must be an integer")


@dataclass(frozen=True)
class ProbabilityAnswer:
    key: str
    value: float | None
    status: AnswerStatus
    confidence: float
    provider_id: str

    def __post_init__(self) -> None:
        _answer_common(self.key, self.value, self.status, self.confidence, self.provider_id)
        if self.value is not None and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise DecisionValidationError("probability value must be numeric")
        if self.value is not None: _prob(self.value, "probability")


@dataclass(frozen=True)
class TaskDecisionProfile:
    task_type: ChoiceAnswer
    complexity: ScoreAnswer
    risk: ScoreAnswer
    architectural_impact: ScoreAnswer
    requires_reasoning: ProbabilityAnswer
    requires_review: ProbabilityAnswer
    requires_qa: ProbabilityAnswer
    requirements_clear: ProbabilityAnswer
    security_sensitive: ProbabilityAnswer
    meaningful_progress: ProbabilityAnswer | None = None
    requirements_satisfied: ProbabilityAnswer | None = None
    another_iteration_useful: ProbabilityAnswer | None = None
    requires_escalation: ProbabilityAnswer | None = None

    def to_dict(self) -> dict[str, Any]:
        def convert(v: Any) -> Any:
            if isinstance(v, Enum): return v.value
            if hasattr(v, "__dataclass_fields__"): return {k: convert(x) for k, x in asdict(v).items()}
            if isinstance(v, tuple): return [convert(x) for x in v]
            return v
        return convert(self)

    @classmethod
    def normalize(cls, payload: Any, phase: str | None = None) -> "TaskDecisionProfile":
        required = {"task_type", "complexity", "risk", "architectural_impact", "requires_reasoning", "requires_review", "requires_qa", "requirements_clear", "security_sensitive"}
        post = {"meaningful_progress", "requirements_satisfied", "another_iteration_useful", "requires_escalation"}
        optional = post if phase is None else (post if phase == "post_execution" else set())
        if phase not in {None, "pre_execution", "post_execution"}:
            raise DecisionValidationError("invalid profile phase")
        expected = required | optional
        if phase is None:
            expected = required if set(payload) <= required else expected
        if not isinstance(payload, dict) or set(payload) != expected:
            raise DecisionValidationError("profile has unexpected or missing keys")
        mapping = {"task_type": ChoiceAnswer, "complexity": ScoreAnswer, "risk": ScoreAnswer, "architectural_impact": ScoreAnswer, "requires_reasoning": ProbabilityAnswer, "requires_review": ProbabilityAnswer, "requires_qa": ProbabilityAnswer, "requirements_clear": ProbabilityAnswer, "security_sensitive": ProbabilityAnswer, "meaningful_progress": ProbabilityAnswer, "requirements_satisfied": ProbabilityAnswer, "another_iteration_useful": ProbabilityAnswer, "requires_escalation": ProbabilityAnswer}
        values = {}
        try:
            for key, typ in mapping.items():
                if key not in payload:
                    values[key] = None
                    continue
                raw = payload[key]
                if key in optional and raw is None:
                    values[key] = None
                    continue
                if not isinstance(raw, dict) or set(raw) != {"key", "value", "status", "confidence", "provider_id"}:
                    raise DecisionValidationError("profile answer has unexpected keys")
                values[key] = typ(raw["key"], raw["value"], AnswerStatus(raw["status"]), raw["confidence"], raw["provider_id"])
        except DecisionValidationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionValidationError("invalid profile answer") from exc
        return cls(**values)


def _answer_common(key: Any, value: Any, status: Any, confidence: Any, provider_id: Any) -> None:
    _text(key, "answer key")
    _text(provider_id, "provider_id")
    if any(token in provider_id.lower() for token in ("model", "openai", "anthropic", "provider:")):
        raise DecisionValidationError("provider_id leaks provider details")
    if not isinstance(status, AnswerStatus):
        raise DecisionValidationError("status must be AnswerStatus")
    _prob(confidence, "confidence")
    if status is AnswerStatus.ANSWERED and value is None:
        raise DecisionValidationError("answered result requires a value")
    if status is not AnswerStatus.ANSWERED and value is not None:
        raise DecisionValidationError("non-answered result must not have a value")


@dataclass(frozen=True)
class DecisionResult:
    answers: tuple[ChoiceAnswer | ScoreAnswer | ProbabilityAnswer, ...]
    schema_version: int = 1

    def validate(self, schema: DecisionSchema) -> None:
        if not isinstance(self.answers, tuple):
            raise DecisionValidationError("answers must be a tuple")
        schema.validate()
        if self.schema_version != schema.version or len(self.answers) != len(schema.questions):
            raise DecisionValidationError("result schema mismatch")
        for question, answer in zip(schema.questions, self.answers):
            if not isinstance(answer, (ChoiceAnswer, ScoreAnswer, ProbabilityAnswer)):
                raise DecisionValidationError("invalid answer object")
            if answer.key != question.key:
                raise DecisionValidationError("answer key mismatch")
            if question.kind is DecisionKind.CHOICE and not isinstance(answer, ChoiceAnswer):
                raise DecisionValidationError("answer kind mismatch")
            if question.kind is DecisionKind.CHOICE and answer.value is not None and answer.value not in question.options:
                raise DecisionValidationError("choice answer is not an option")
            if question.kind is DecisionKind.SCORE and (not isinstance(answer, ScoreAnswer) or (answer.value is not None and answer.value not in question.scale)):
                raise DecisionValidationError("score answer mismatch")
            if question.kind is DecisionKind.PROBABILITY and not isinstance(answer, ProbabilityAnswer):
                raise DecisionValidationError("answer kind mismatch")

    @classmethod
    def normalize(cls, payload: dict[str, Any], schema: DecisionSchema) -> "DecisionResult":
        if not isinstance(payload, dict) or set(payload) != {"answers", "schema_version"} or not isinstance(payload.get("answers"), list):
            raise DecisionValidationError("result has unexpected keys")
        if isinstance(payload["schema_version"], bool) or not isinstance(payload["schema_version"], int):
            raise DecisionValidationError("invalid result schema version")
        answers = []
        if len(payload["answers"]) != len(schema.questions):
            raise DecisionValidationError("result answer count mismatch")
        for raw, question in zip(payload["answers"], schema.questions):
            allowed = {"key", "value", "status", "confidence", "provider_id"}
            if not isinstance(raw, dict) or set(raw) != allowed:
                raise DecisionValidationError("answer has unexpected keys")
            try:
                status = AnswerStatus(raw["status"])
                typ = {DecisionKind.CHOICE: ChoiceAnswer, DecisionKind.SCORE: ScoreAnswer, DecisionKind.PROBABILITY: ProbabilityAnswer}[question.kind]
                answers.append(typ(raw["key"], raw["value"], status, raw["confidence"], raw["provider_id"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise DecisionValidationError("invalid answer") from exc
        result = cls(tuple(answers), payload["schema_version"])
        result.validate(schema)
        return result


def canonical_json(value: Any) -> str:
    """Return deterministic compact JSON for contract values."""
    def convert(item: Any) -> Any:
        if isinstance(item, Enum): return item.value
        if hasattr(item, "to_dict"): return convert(item.to_dict())
        if hasattr(item, "__dataclass_fields__"): return {k: convert(v) for k, v in asdict(item).items()}
        if isinstance(item, dict): return {k: convert(v) for k, v in item.items()}
        if isinstance(item, (tuple, list)): return [convert(v) for v in item]
        return item
    value = convert(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
