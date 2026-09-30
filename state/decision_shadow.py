"""Best-effort, shadow-only coordinator for the Decision Plane."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from . import decision as _decision
    from .decision import (BoundedDecisionContext, ChoiceQuestion, DecisionRequest,
                           DecisionSchema, Fact, ProbabilityQuestion, ScoreQuestion, DecisionValidationError)
    from .decision_audit import DecisionAudit
    from .decision_policy import DecisionPolicy, PolicyConfig, PolicyFacts
    from .loop_detector import LoopDetector, LoopLimits
    from .decision_providers import DecisionProviderChain, DeterministicSafeProvider, MockDecisionProvider
    from .decision_jev import JevDecisionProvider, JevHttpConfig
except ImportError:
    import decision as _decision
    from decision import (BoundedDecisionContext, ChoiceQuestion, DecisionRequest,
                          DecisionSchema, Fact, ProbabilityQuestion, ScoreQuestion, DecisionValidationError)
    from decision_audit import DecisionAudit
    from decision_policy import DecisionPolicy, PolicyConfig, PolicyFacts
    from loop_detector import LoopDetector, LoopLimits
    from decision_providers import DecisionProviderChain, DeterministicSafeProvider, MockDecisionProvider
    from decision_jev import JevDecisionProvider, JevHttpConfig


class DecisionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ShadowObservationDiagnostic:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ContextLimits:
    max_questions: int = 12
    max_metadata_facts: int = 32
    max_text_chars: int = 2000
    max_bytes: int = 16 * 1024


@dataclass(frozen=True)
class DecisionConfig:
    enabled: bool = False
    mode: str = "shadow"
    providers: tuple[str, ...] = ("deterministic-safe",)
    audit_path: str = ".agent-managed/runtime/decision-audit.jsonl"
    policy: PolicyConfig = PolicyConfig()
    context: ContextLimits = ContextLimits()
    jev: JevHttpConfig = JevHttpConfig()

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any] | None) -> "DecisionConfig":
        raw = (manifest or {}).get("decision") or {}
        if not isinstance(raw, Mapping):
            raise DecisionConfigError("decision config must be an object")
        allowed = {"enabled", "mode", "providers", "audit_path", "policy", "context", "jev"}
        if set(raw) - allowed:
            raise DecisionConfigError("unknown decision config key")
        enabled = raw.get("enabled", False)
        mode = raw.get("mode", "shadow")
        if not isinstance(enabled, bool) or mode not in {"disabled", "shadow"}:
            raise DecisionConfigError("decision mode must be disabled or shadow")
        names = raw.get("providers", ["deterministic-safe"])
        if not isinstance(names, (list, tuple)) or not names or any(not isinstance(x, str) or not x.strip() for x in names) or len(set(names)) != len(names):
            raise DecisionConfigError("providers must be unique non-empty names")
        if any(x not in {"deterministic-safe", "mock", "jev"} for x in names):
            raise DecisionConfigError("unknown decision provider")
        path = raw.get("audit_path", cls.audit_path)
        if not isinstance(path, str) or not path.strip():
            raise DecisionConfigError("audit_path must be a relative project path")
        p = Path(path)
        if p.is_absolute() or ".." in p.parts:
            raise DecisionConfigError("audit_path must be a relative project path")
        pol = raw.get("policy", {})
        ctx = raw.get("context", {})
        jev_raw = raw.get("jev", {})
        if not isinstance(pol, Mapping) or not isinstance(ctx, Mapping) or not isinstance(jev_raw, Mapping):
            raise DecisionConfigError("policy and context must be objects")
        if set(jev_raw) - {"endpoint", "model", "timeout"}:
            raise DecisionConfigError("unknown Jev config key")
        if set(pol) - set(PolicyConfig.__dataclass_fields__) or set(ctx) - set(ContextLimits.__dataclass_fields__):
            raise DecisionConfigError("unknown policy or context key")
        try:
            policy = PolicyConfig(**dict(pol))
            limits = ContextLimits(**dict(ctx))
            jev = JevHttpConfig(timeout_seconds=jev_raw.get("timeout", JevHttpConfig.timeout_seconds),
                                endpoint=jev_raw.get("endpoint", JevHttpConfig.endpoint),
                                model=jev_raw.get("model", JevHttpConfig.model))
            jev.validate()
        except (TypeError, ValueError) as exc:
            raise DecisionConfigError("invalid policy or context value") from exc
        if any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in (limits.max_questions, limits.max_metadata_facts, limits.max_text_chars, limits.max_bytes)):
            raise DecisionConfigError("context bounds must be positive integers")
        if limits.max_questions < 12:
            raise DecisionConfigError("max_questions must be at least the schema requirement (12)")
        if limits.max_questions > 12 or limits.max_metadata_facts > 32 or limits.max_text_chars > 2000 or limits.max_bytes > 16 * 1024:
            raise DecisionConfigError("context bounds exceed hard limits")
        return cls(bool(enabled and mode == "shadow"), mode, tuple(names), path, policy, limits, jev)


def _value(v: Any, limit: int) -> Any:
    if isinstance(v, str):
        return v[:limit]
    return v


def build_decision_context(task: Any, route: Any = None, current_state: Any = None, capsule: Any = None, limits: ContextLimits | None = None) -> BoundedDecisionContext:
    limits = limits or ContextLimits()
    def get(obj: Any, key: str, default: Any = None) -> Any:
        return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)
    objective = _value(get(task, "objective", get(task, "summary", "decision observation")), limits.max_text_chars)
    requirements = get(task, "requirements", ()) or ()
    if not isinstance(requirements, (list, tuple)) or any(not isinstance(x, str) for x in requirements):
        raise DecisionConfigError("requirements must be strings")
    if _decision._safe_fact_text is not None:
        try:
            _decision._safe_fact_text(str(objective), "objective")
            for requirement in requirements:
                _decision._safe_fact_text(requirement, "requirement")
        except DecisionValidationError as exc:
            raise DecisionConfigError(str(exc)) from exc
    facts: list[Fact] = []
    sources = (task, route, current_state)
    for obj in sources:
        if isinstance(obj, Mapping):
            for key in sorted(obj):
                if key in {"objective", "summary", "requirements", "prompt", "transcript", "reasoning", "session"} or len(facts) >= limits.max_metadata_facts:
                    continue
                value = obj[key]
                if isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and not math.isfinite(value)):
                    facts.append(Fact(str(key), _value(value, limits.max_text_chars)))
    # Deterministic final-size bounding: text, then facts, then requirements.
    def make(reqs, fs):
        return BoundedDecisionContext(objective, tuple(_value(x, limits.max_text_chars) for x in reqs), tuple(fs))
    reqs, fs = requirements[:32], facts[:limits.max_metadata_facts]
    while len(_decision.canonical_json(make(reqs, fs)).encode()) > limits.max_bytes:
        if len(objective) > 1:
            objective = objective[:-1]
        elif fs:
            fs.pop()
        elif reqs:
            reqs.pop()
        else:
            break
    context = make(reqs, fs)
    context.validate()
    return context


def _schema(phase: str = "pre_execution") -> DecisionSchema:
    keys = ("requires_reasoning", "requires_review", "requires_qa", "requirements_clear", "security_sensitive")
    if phase == "post_execution":
        keys += ("meaningful_progress", "requirements_satisfied", "another_iteration_useful", "requires_escalation")
    return DecisionSchema((ChoiceQuestion("task_type", ("bug", "feature", "maintenance", "unknown")), ScoreQuestion("complexity", (1, 2, 3, 4, 5)), ScoreQuestion("risk", (1, 2, 3, 4, 5)), ScoreQuestion("architectural_impact", (1, 2, 3, 4, 5)), *(ProbabilityQuestion(k) for k in keys)))


def _run(config: DecisionConfig, context: BoundedDecisionContext, phase: str, observation_id: str) -> tuple[Any, Any]:
    schema = _schema(phase)
    request = DecisionRequest.from_context(schema, context, observation_id=observation_id, phase=phase)
    def make(name: str) -> Any:
        if name == "jev":
            return JevDecisionProvider(config=config.jev)
        if name == "mock":
            return MockDecisionProvider([])
        return DeterministicSafeProvider()
    result = DecisionProviderChain(tuple(make(name) for name in config.providers)).evaluate(request)
    answers = [{"key": a.key, "value": a.value, "status": a.status.value,
                "confidence": a.confidence, "provider_id": a.provider_id} for a in result.result.answers]
    keys = [q.key for q in schema.questions]
    profile = _decision.TaskDecisionProfile.normalize(dict(zip(keys, answers)), phase=phase)
    confidences = [a.confidence for a in result.result.answers]
    summary = {"min": min(confidences, default=0.0), "mean": sum(confidences) / len(confidences) if confidences else 0.0,
               "perAnswer": confidences}
    return result, (profile, summary)


def observe_pre(config: DecisionConfig, task: Any, route: Any = None, current_state: Any = None, capsule: Any = None, *, audit: DecisionAudit | None = None) -> dict[str, Any] | None:
    if not config.enabled or config.mode != "shadow":
        return None
    try:
        def get(obj: Any, key: str, default: Any = None) -> Any:
            return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)

        context = build_decision_context(task, route, current_state, capsule, config.context)
        request = DecisionRequest.from_context(
            _schema("pre_execution"),
            context,
            observation_id=str(get(task, "id", "observation")),
        )
        result, (profile, confidence) = _run(config, context, "pre_execution", request.observation_id)
        history = current_state.get("history", ()) if isinstance(current_state, Mapping) else ()
        compact_history = [{k: item[k] for k in ("command", "error", "source", "gate", "state", "retry_count") if k in item} for item in history if isinstance(item, Mapping)]
        execution = (current_state or {}).get("executionPolicy", {}) if isinstance(current_state, Mapping) else {}
        aliases = {"maxSameGateFailure": "gate_window", "maxNoProgressRounds": "no_progress_window", "maxReviewIterations": "retry_ceiling"}
        values = {aliases.get(k, k): v for k, v in execution.items() if isinstance(v, int) and not isinstance(v, bool) and v > 0}
        limits = LoopLimits(**{k: values[k] for k in LoopLimits.__dataclass_fields__ if k in values})
        finding = LoopDetector().evaluate(compact_history, limits)
        route_class = route.get("class", {}) if isinstance(route, Mapping) else {}
        if not route_class and isinstance(route, Mapping):
            route_class = route
        facts = PolicyFacts(
            complexity=str(route_class.get("complexity", "LOW")).upper(),
            risk=str(route_class.get("risk", "LOW")).upper(),
            require_review=bool(route_class.get("requiresReview", False) or route_class.get("requires_review", False)),
            require_qa=bool(route_class.get("requiresQa", False) or route_class.get("requires_qa", False)),
            gate_failed=any(bool(item.get("gate_failed") or item.get("result") == "FAIL") for item in compact_history),
            convergence_stop=finding.looping,
        )
        recommendation = DecisionPolicy(config.policy).evaluate(profile, facts)
        # Audit stores only non-sensitive facts; profile answer keys include
        # policy terms (for example ``requires_reasoning``) rejected by the
        # audit metric filter, so retain the bounded summary instead.
        record = {"feature": str(get(task, "feature", "decision-plane")), "task": request.observation_id,
                  "provider": {"id": result.provider_id, "model": result.metadata.model if result.metadata else None},
                  "profile": profile.to_dict(), "confidence": confidence,
                  "policyRecommendation": {"executionTier": recommendation.execution_tier.value,
                                             "modelClassFloor": recommendation.model_class_floor,
                                             "invokeOrchestrator": recommendation.invoke_orchestrator,
                                             "requireReview": recommendation.require_review,
                                             "requireQa": recommendation.require_qa,
                                             "stopOrEscalate": recommendation.stop_or_escalate,
                                             "reasonCodes": list(recommendation.reason_codes)},
                  "authoritativeDecision": {"class": route_class, "provider": get(route, "provider"),
                                             "verify": get(route, "verify"), "roles": get(route, "roles"), "gates": get(route, "gates")},
                   "usage": {"latencyMs": result.metadata.latency_ms if result.metadata else None,
                              "inputTokens": result.metadata.usage.input_tokens if result.metadata and result.metadata.usage else None,
                              "outputTokens": result.metadata.usage.output_tokens if result.metadata and result.metadata.usage else None,
                              "cost": None},
                  "mismatch": {"authoritative": False, "codes": []}}
        correlation = (audit or DecisionAudit(audit_path=config.audit_path)).record_pre(record)
        record["correlation_id"] = correlation
        return record
    except Exception as exc:
        return {"feature": "decision-plane", "diagnostic": ShadowObservationDiagnostic("internal_failure", type(exc).__name__).to_dict()}


def observe_post(config: DecisionConfig, comparison: Mapping[str, Any], *, root: Path | str = ".", correlation_id: str | None = None, audit: DecisionAudit | None = None) -> None:
    if not config.enabled or config.mode != "shadow":
        return
    try:
        if not isinstance(comparison, Mapping):
            raise DecisionConfigError("comparison must be an object")
        payload = dict(comparison)
        task = payload.get("taskContext", payload.get("task", {}))
        eventual = payload.get("eventualFacts", payload)
        context = build_decision_context(task, eventual, limits=config.context)
        result, (profile, confidence) = _run(config, context, "post_execution", str(payload.get("taskId", "observation")))
        raw_usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
        receipt_model = payload.get("model")
        receipt_usage = {key: raw_usage.get(key) for key in
                         ("latencyMs", "inputTokens", "outputTokens", "cost")}
        metadata = result.metadata
        usage = {
            "latencyMs": metadata.latency_ms if metadata else raw_usage.get("latencyMs"),
            "inputTokens": metadata.usage.input_tokens if metadata and metadata.usage else raw_usage.get("inputTokens"),
            "outputTokens": metadata.usage.output_tokens if metadata and metadata.usage else raw_usage.get("outputTokens"),
            "cost": raw_usage.get("cost", raw_usage.get("costMicrounits")),
        }
        # Jev metadata describes the shadow provider, not the authoritative
        # developer receipt.  Keep receipt inputs untouched while auditing the
        # provider model/usage when the chain supplies it.
        if metadata and metadata.model:
            payload["model"] = metadata.model
        payload["usage"] = usage
        payload["comparison"] = {"postProfile": profile.to_dict(), "confidence": confidence,
                                  "policyReasonCodes": ["post_evaluation_complete"],
                                  "authoritativePreDecision": payload.get("authoritativePreDecision", {}),
                                  "eventual": {"role": payload.get("role"), "result": payload.get("eventualResult"),
                                                 "gates": payload.get("gates"), "model": receipt_model, "usage": receipt_usage},
                                  "mismatches": payload.get("mismatches", [])}
        # Context used for evaluation is never part of the fact-only audit.
        payload.pop("taskContext", None)
        payload.pop("eventualFacts", None)
        task_id = payload.pop("taskId", None)
        if "task" not in payload:
            payload["task"] = task_id or "observation"
        payload.pop("authoritativePreDecision", None)
        payload.pop("role", None)
        payload.pop("gates", None)
        payload.setdefault("feature", "decision-plane")
        if correlation_id is not None:
            payload["correlationId"] = correlation_id
        (audit or DecisionAudit(root=root, audit_path=config.audit_path)).record_post(payload)
    except Exception:
        return
