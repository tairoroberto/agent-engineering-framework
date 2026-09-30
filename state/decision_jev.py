"""Official, one-shot stdlib HTTP adapter for TypeSafe Jev."""
from __future__ import annotations

import json
import http.client
import math
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

try:
    from .decision import DecisionKind, DecisionRequest, DecisionResult, canonical_json
    from .decision_providers import (DecisionProviderCapabilities, ProviderError,
        ProviderEvaluation, ProviderFailure, ProviderResultMetadata, ProviderStatus,
        ProviderUsage)
except ImportError:
    from decision import DecisionKind, DecisionRequest, DecisionResult, canonical_json
    from decision_providers import (DecisionProviderCapabilities, ProviderError,
        ProviderEvaluation, ProviderFailure, ProviderResultMetadata, ProviderStatus,
        ProviderUsage)

Transport = Callable[[DecisionRequest], Any]
Mapper = Callable[[Any, DecisionRequest], dict[str, Any]]
MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


@dataclass(frozen=True)
class JevHttpConfig:
    endpoint: str = DEFAULT_ENDPOINT
    model: str = "jev-latest"
    timeout_seconds: float = 10.0

    def validate(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint.strip():
            raise ValueError("invalid Jev endpoint")
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("invalid Jev endpoint")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 255:
            raise ValueError("invalid Jev model")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds) or not 0.1 <= self.timeout_seconds <= 30.0:
            raise ValueError("invalid Jev timeout")


_DESCRIPTIONS = {
    "task_type": "Classify the task's primary work type.",
    "complexity": "Estimate implementation complexity from localized work to system-wide coordination.",
    "risk": "Estimate delivery and operational risk from negligible consequences to critical consequences.",
    "architectural_impact": "Estimate architectural impact from no meaningful change to foundational change.",
    "requires_reasoning": "Whether deeper reasoning is needed.", "requires_review": "Whether independent review is needed.",
    "requires_qa": "Whether additional QA is needed.", "requirements_clear": "Whether requirements are sufficiently clear.",
    "security_sensitive": "Whether the task handles security-sensitive material.", "meaningful_progress": "Whether execution made meaningful progress.",
    "requirements_satisfied": "Whether requirements are satisfied.", "another_iteration_useful": "Whether another iteration is useful.",
    "requires_escalation": "Whether the result requires escalation.",
}

_CHOICE_CRITERIA = {
    "bug": "A defect fix or regression correction.",
    "feature": "A new user-visible capability.",
    "maintenance": "Refactoring, configuration, documentation, or upkeep without new behavior.",
    "unknown": "Insufficient or ambiguous information to classify the task.",
}

_SCORE_CRITERIA = {
    "complexity": {
        1: "Localized change in one small area with straightforward implementation.",
        2: "Small change spanning a few related units with limited coordination.",
        3: "Moderate change across multiple units requiring deliberate integration.",
        4: "Broad change across subsystems requiring substantial coordination and validation.",
        5: "System-wide change with complex cross-cutting implementation and coordination.",
    },
    "risk": {
        1: "Negligible chance of harmful delivery or operational consequences.",
        2: "Low chance of limited, readily recoverable delivery or operational consequences.",
        3: "Moderate chance of contained delivery or operational consequences requiring mitigation.",
        4: "High chance of significant delivery or operational consequences requiring active safeguards.",
        5: "Critical chance or severity of delivery or operational consequences requiring exceptional safeguards.",
    },
    "architectural_impact": {
        1: "No meaningful architectural, interface, or contract change.",
        2: "Localized architectural change with no broad interface or contract implications.",
        3: "Change affecting several related components or a bounded contract.",
        4: "Cross-subsystem architectural change affecting important interfaces or contracts.",
        5: "Foundational change that reshapes system boundaries, interfaces, or contracts.",
    },
}


def build_payload(request: DecisionRequest, config: JevHttpConfig | None = None) -> dict[str, Any]:
    request.validate()
    _validate_canonical_request(request)
    config = config or JevHttpConfig()
    config.validate()
    questions: dict[str, Any] = {}
    for question in request.schema.questions:
        description = _DESCRIPTIONS[question.key]
        if question.kind is DecisionKind.CHOICE:
            questions[question.key] = {"type": "choice", "instructions": description, "criteria": {option: _CHOICE_CRITERIA[option] for option in question.options}}
        elif question.kind is DecisionKind.SCORE:
            questions[question.key] = {"type": "score", "instructions": description, "criteria": [_SCORE_CRITERIA[question.key][value] for value in question.scale]}
        else:
            questions[question.key] = {"type": "noul", "instructions": description, "criteria": {"true": "Yes", "false": "No"}}
    context = request.context
    state = {"objective": context.objective, "requirements": list(context.requirements), "facts": {fact.key: fact.value for fact in context.facts}}
    return {"state": state, "model": config.model, "questions": questions}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_canonical_request(request: DecisionRequest) -> None:
    pre_keys = (
        "task_type", "complexity", "risk", "architectural_impact",
        "requires_reasoning", "requires_review", "requires_qa",
        "requirements_clear", "security_sensitive",
    )
    phase_keys = {
        "pre_execution": pre_keys,
        "post_execution": pre_keys + (
            "meaningful_progress", "requirements_satisfied",
            "another_iteration_useful", "requires_escalation",
        ),
    }
    if tuple(question.key for question in request.schema.questions) != phase_keys.get(request.phase):
        raise ValueError("non-canonical Jev question sequence")
    expected = {
        "task_type": (DecisionKind.CHOICE, ("bug", "feature", "maintenance", "unknown")),
        "complexity": (DecisionKind.SCORE, (1, 2, 3, 4, 5)),
        "risk": (DecisionKind.SCORE, (1, 2, 3, 4, 5)),
        "architectural_impact": (DecisionKind.SCORE, (1, 2, 3, 4, 5)),
    }
    expected.update({key: (DecisionKind.PROBABILITY, ()) for key in (
        "requires_reasoning", "requires_review", "requires_qa", "requirements_clear",
        "security_sensitive", "meaningful_progress", "requirements_satisfied",
        "another_iteration_useful", "requires_escalation")})
    for question in request.schema.questions:
        kind, bounds = expected.get(question.key, (None, None))
        if kind is None or question.kind is not kind:
            raise ValueError("non-canonical Jev question")
        if kind is DecisionKind.CHOICE and question.options != bounds:
            raise ValueError("invalid Jev choice options")
        if kind is DecisionKind.SCORE and question.scale != bounds:
            raise ValueError("invalid Jev score scale")


def _valid_api_key(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and not any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value
    )


def _json_loads(raw: bytes) -> Any:
    def reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_pairs)


def normalize_response(payload: Any, request: DecisionRequest, elapsed_ms: int = 0, *, forbidden_credential: str | None = None) -> ProviderEvaluation:
    try:
        _validate_canonical_request(request)
        if not isinstance(payload, dict) or list(payload) != ["model", "answers", "usage"] or not isinstance(payload["answers"], dict): raise ValueError
        model, answers, usage = payload["model"], payload["answers"], payload["usage"]
        if not isinstance(model, str) or not model.strip() or len(model) > 255 or not isinstance(usage, dict) or list(usage) != ["input_tokens", "output_tokens"]: raise ValueError
        if forbidden_credential and forbidden_credential in model: raise ValueError
        if any(isinstance(usage[k], bool) or type(usage[k]) is not int or usage[k] < 0 or usage[k] > 1_000_000 for k in usage): raise ValueError
        if list(answers) != [q.key for q in request.schema.questions]: raise ValueError
        normalized = []
        for question in request.schema.questions:
            raw = answers[question.key]
            expected_keys = ("type", "selection", "probabilities", "confidence") if question.kind is DecisionKind.CHOICE else ("type", "score", "legend", "probabilities", "confidence") if question.kind is DecisionKind.SCORE else ("type", "noul")
            if not isinstance(raw, dict) or list(raw) != list(expected_keys): raise ValueError
            if question.kind is DecisionKind.CHOICE:
                if raw["type"] != "choice" or not isinstance(raw["probabilities"], dict) or list(raw["probabilities"]) != list(question.options) or not _finite(raw["confidence"]): raise ValueError
                if not isinstance(raw["selection"], str) or raw["selection"] not in question.options: raise ValueError
                if abs(sum(raw["probabilities"].values()) - 1) > 1e-6 or any(not _finite(v) or not 0 <= v <= 1 for v in raw["probabilities"].values()): raise ValueError
                value, confidence = raw["selection"], float(raw["confidence"])
                kind = "choice"
            elif question.kind is DecisionKind.SCORE:
                expected_legend = {str(i): _SCORE_CRITERIA[question.key][question.scale[i]] for i in range(len(question.scale))}
                expected_indices = [str(i) for i in range(len(question.scale))]
                if raw["type"] != "score" or not isinstance(raw["legend"], dict) or not isinstance(raw["probabilities"], dict) or list(raw["legend"]) != expected_indices or list(raw["probabilities"]) != expected_indices or raw["legend"] != expected_legend or not _finite(raw["score"]) or not _finite(raw["confidence"]): raise ValueError
                if not 0 <= raw["score"] <= len(question.scale) - 1: raise ValueError
                if abs(sum(raw["probabilities"].values()) - 1) > 1e-6 or any(not _finite(v) or not 0 <= v <= 1 for v in raw["probabilities"].values()): raise ValueError
                expected_score = sum(index * raw["probabilities"][str(index)] for index in range(len(question.scale)))
                if not math.isclose(raw["score"], expected_score, rel_tol=1e-9, abs_tol=1e-9): raise ValueError
                value, confidence = question.scale[min(len(question.scale) - 1, math.floor(raw["score"] + 0.5))], float(raw["confidence"])
                kind = "score"
            else:
                if raw["type"] != "noul" or not _finite(raw["noul"]) or not 0 <= raw["noul"] <= 1: raise ValueError
                value, confidence, kind = float(raw["noul"]), abs(2 * float(raw["noul"]) - 1), "probability"
            normalized.append({"key": question.key, "value": value, "status": "answered", "confidence": confidence, "provider_id": "jev"})
        result = DecisionResult.normalize({"answers": normalized, "schema_version": request.schema.version}, request.schema)
        return ProviderEvaluation(result, ProviderResultMetadata(model, ProviderUsage(usage["input_tokens"], usage["output_tokens"]), max(0, elapsed_ms)))
    except Exception as error:
        if isinstance(error, ProviderError): raise
        raise ProviderError(ProviderFailure.INVALID) from None


class JevDecisionProvider:
    provider_id = "jev"
    def __init__(self, transport: Transport | None = None, mapper: Mapper | None = None, config: JevHttpConfig | None = None, *, environ: dict[str, str] | None = None, opener: Any | None = None) -> None:
        self._legacy_transport, self._legacy_mapper = transport, mapper
        self._config, self._environ = config or JevHttpConfig(), environ if environ is not None else os.environ
        self._opener = opener
        self._config.validate()

    def capabilities(self) -> DecisionProviderCapabilities:
        legacy = self._legacy_transport is not None and self._legacy_mapper is not None
        partial_legacy = (self._legacy_transport is None) != (self._legacy_mapper is None)
        available = legacy or (not partial_legacy and _valid_api_key(self._environ.get("TYPESAFE_API_KEY", "")))
        return DecisionProviderCapabilities(self.provider_id, tuple(DecisionKind), ProviderStatus.AVAILABLE if available else ProviderStatus.UNAVAILABLE, 16 * 1024, True, True)

    def evaluate(self, request: DecisionRequest) -> Any:
        request.validate()
        try:
            _validate_canonical_request(request)
        except (ValueError, TypeError, AttributeError):
            raise ProviderError(ProviderFailure.INVALID) from None
        if (self._legacy_transport is None) != (self._legacy_mapper is None):
            raise ProviderError(ProviderFailure.UNSUPPORTED)
        if self._legacy_transport is not None and self._legacy_mapper is not None:
            try:
                payload = self._legacy_transport(request)
            except ProviderError: raise
            except Exception: raise ProviderError(ProviderFailure.ERROR) from None
            try:
                return DecisionResult.normalize(self._legacy_mapper(payload, request), request.schema)
            except ProviderError: raise
            except Exception: raise ProviderError(ProviderFailure.INVALID) from None
        key = self._environ.get("TYPESAFE_API_KEY", "")
        if not _valid_api_key(key): raise ProviderError(ProviderFailure.UNAVAILABLE)
        body = json.dumps(build_payload(request, self._config), separators=(",", ":"), ensure_ascii=True).encode()
        req = urllib.request.Request(self._config.endpoint, data=body, method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        started = time.monotonic()
        response = None
        try:
            opener = self._opener or urllib.request.build_opener(_NoRedirectHandler())
            response = opener.open(req, timeout=self._config.timeout_seconds)
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if type(status) is not int: raise ProviderError(ProviderFailure.ERROR)
            if 300 <= status < 400: raise ProviderError(ProviderFailure.ERROR)
            if status in (401, 429, 529): raise ProviderError(ProviderFailure.UNAVAILABLE)
            if status == 422: raise ProviderError(ProviderFailure.INVALID)
            if status < 200 or status >= 300: raise ProviderError(ProviderFailure.ERROR)
            headers = getattr(response, "headers", {})
            if not hasattr(headers, "get"): raise ProviderError(ProviderFailure.INVALID)
            declared = headers.get("Content-Length")
            if declared is not None:
                if not isinstance(declared, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)", declared):
                    raise ProviderError(ProviderFailure.INVALID)
                if int(declared) > MAX_RESPONSE_BYTES: raise ProviderError(ProviderFailure.INVALID)
            content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
            if content_type != "application/json" and not (content_type.startswith("application/") and content_type.endswith("+json")):
                raise ProviderError(ProviderFailure.INVALID)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES: raise ProviderError(ProviderFailure.INVALID)
            if declared is not None and int(declared) != len(raw): raise ProviderError(ProviderFailure.INVALID)
            payload = _json_loads(raw)
            return normalize_response(payload, request, int((time.monotonic() - started) * 1000), forbidden_credential=key)
        except ProviderError: raise
        except urllib.error.HTTPError as error:
            response = error
            raise ProviderError(ProviderFailure.UNAVAILABLE if error.code in (401, 429, 529) else ProviderFailure.INVALID if error.code == 422 else ProviderFailure.ERROR) from None
        except (TimeoutError, socket.timeout): raise ProviderError(ProviderFailure.TIMEOUT) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)): raise ProviderError(ProviderFailure.TIMEOUT) from None
            raise ProviderError(ProviderFailure.ERROR) from None
        except (http.client.HTTPException, http.client.IncompleteRead, ConnectionError, OSError):
            raise ProviderError(ProviderFailure.ERROR) from None
        except (RecursionError, UnicodeError, json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
            if response is None:
                raise ProviderError(ProviderFailure.ERROR) from None
            raise ProviderError(ProviderFailure.INVALID) from None
        except Exception:
            raise ProviderError(ProviderFailure.ERROR) from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    raise ProviderError(ProviderFailure.ERROR) from None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        return None
