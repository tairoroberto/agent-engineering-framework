"""Fact-only, best-effort audit storage for shadow decision observations."""
from __future__ import annotations

import hashlib
import json
import os
import importlib.util
import re
from pathlib import Path
from typing import Any

try:
    from . import state as state_tool
    from .routing import METRIC_FORBIDDEN
    from .decision import TaskDecisionProfile
except ImportError:  # direct ``python state/decision_audit.py`` compatibility
    _spec = importlib.util.spec_from_file_location("agent_state_runtime", Path(__file__).with_name("state.py"))
    if _spec is None or _spec.loader is None:
        raise
    state_tool = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(state_tool)
    from routing import METRIC_FORBIDDEN
    from decision import TaskDecisionProfile


MAX_BYTES = 16 * 1024
MAX_ITEMS = 64
_PRE_REQUIRED = {
    "feature", "task", "provider", "profile", "confidence",
    "policyRecommendation", "authoritativeDecision", "usage", "mismatch",
}
_PRE_ALLOWED = _PRE_REQUIRED
_POST_REQUIRED = {"feature", "task", "correlationId", "eventualResult", "comparison", "usage", "model", "orphanedPreObservation"}
_POST_ALLOWED = _POST_REQUIRED
_FORBIDDEN_CLASSES = {"payload", "request", "response", "diff", "full-log", "full_log", "log", "context"}
_USAGE_KEYS = {"latencyMs", "inputTokens", "outputTokens", "cost"}
_POLICY_KEYS = {"executionTier", "modelClassFloor", "invokeOrchestrator", "requireReview", "requireQa", "stopOrEscalate", "reasonCodes"}
_ROUTE_KEYS = {"class", "provider", "verify", "roles", "gates"}
_COMPARISON_KEYS = {"postProfile", "confidence", "policyReasonCodes", "authoritativePreDecision", "eventual", "mismatches"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def _validate(value: Any, path: str = "record") -> None:
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS:
            raise ValueError(f"{path} has too many fields")
        for key, child in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 200:
                raise ValueError(f"invalid audit key at {path}")
            if key.lower().replace("-", "_") in _FORBIDDEN_CLASSES:
                raise ValueError(f"raw audit payload class is forbidden: {key}")
            if (path == "record" and METRIC_FORBIDDEN.search(key)) or state_tool.contains_credential(key):
                raise ValueError(f"forbidden audit key: {key}")
            _validate(child, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) > MAX_ITEMS:
            raise ValueError(f"{path} has too many items")
        for index, child in enumerate(value):
            _validate(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) > 2000 or state_tool.contains_credential(value):
            raise ValueError(f"unsafe audit value at {path}")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ValueError(f"unsupported audit value at {path}")


def sanitize_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate and copy a bounded JSON fact record; never redact silently."""
    if not isinstance(record, dict):
        raise ValueError("audit record must be an object")
    result = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    _validate(result)
    if len(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("audit record exceeds 16KiB")
    return result


def _validate_phase(record: dict[str, Any], phase: str) -> dict[str, Any]:
    safe = sanitize_audit_record(record)
    allowed = _PRE_ALLOWED if phase == "pre_execution" else _POST_ALLOWED
    if set(safe) - allowed:
        raise ValueError("audit record has unexpected fields")
    if any(str(key).lower().replace("-", "_") in _FORBIDDEN_CLASSES for key in safe):
        raise ValueError("raw audit payload class is forbidden")
    required = _PRE_REQUIRED if phase == "pre_execution" else _POST_REQUIRED
    if not required <= set(safe):
        raise ValueError(f"{phase} record is missing required fields")
    if any(not isinstance(safe[key], str) or not _IDENTIFIER.fullmatch(safe[key]) or ".." in safe[key] for key in ("feature", "task")):
        raise ValueError("feature and task must be safe identifiers")
    if phase == "pre_execution":
        if not isinstance(safe["provider"], dict) or set(safe["provider"]) != {"id", "model"}:
            raise ValueError("provider must be an object")
        if not isinstance(safe["profile"], dict):
            raise ValueError("profile must be an object")
        if not isinstance(safe["policyRecommendation"], dict):
            raise ValueError("policyRecommendation must be an object")
        if not isinstance(safe["authoritativeDecision"], dict):
            raise ValueError("authoritativeDecision must be an object")
        if not isinstance(safe["usage"], dict) or not isinstance(safe["mismatch"], dict):
            raise ValueError("usage and mismatch must be objects")
        provider = safe["provider"]
        if not isinstance(provider["id"], str) or (provider["model"] is not None and not isinstance(provider["model"], str)):
            raise ValueError("invalid provider shape")
        try:
            pre_profile = {k: v for k, v in safe["profile"].items() if v is not None}
            TaskDecisionProfile.normalize(pre_profile, "pre_execution")
        except Exception as exc:
            raise ValueError("invalid pre profile") from exc
        _validate_confidence(safe["confidence"])
        policy = safe["policyRecommendation"]
        if set(policy) != _POLICY_KEYS or not isinstance(policy["executionTier"], str) or not isinstance(policy["modelClassFloor"], str) or any(not isinstance(policy[k], bool) for k in ("invokeOrchestrator", "requireReview", "requireQa", "stopOrEscalate")) or not isinstance(policy["reasonCodes"], list) or not policy["reasonCodes"] or any(not isinstance(x, str) for x in policy["reasonCodes"]):
            raise ValueError("invalid policy recommendation shape")
        route = safe["authoritativeDecision"]
        if set(route) != _ROUTE_KEYS or not isinstance(route["class"], dict) or (route["provider"] is not None and not isinstance(route["provider"], (dict, str))) or (route["verify"] is not None and not isinstance(route["verify"], (dict, list, str, bool))) or (route["roles"] is not None and not isinstance(route["roles"], (dict, list))) or (route["gates"] is not None and not isinstance(route["gates"], (dict, list))):
            raise ValueError("invalid authoritative decision shape")
        _validate_usage(safe["usage"])
        mismatch = safe["mismatch"]
        if set(mismatch) != {"authoritative", "codes"} or not isinstance(mismatch["authoritative"], bool) or not isinstance(mismatch["codes"], list) or any(not isinstance(x, str) for x in mismatch["codes"]):
            raise ValueError("invalid mismatch shape")
    else:
        if not isinstance(safe["comparison"], dict) or set(safe["comparison"]) != _COMPARISON_KEYS or not isinstance(safe["usage"], dict):
            raise ValueError("comparison and usage must be objects")
        if not isinstance(safe["comparison"]["policyReasonCodes"], list) or not safe["comparison"]["policyReasonCodes"] or any(not _safe_reason_code(x) for x in safe["comparison"]["policyReasonCodes"]):
            raise ValueError("post policy reason codes are required")
        eventual = safe["comparison"]["eventual"]
        if not isinstance(eventual, dict) or set(eventual) != {"role", "result", "gates", "model", "usage"}:
            raise ValueError("invalid eventual comparison shape")
        try:
            TaskDecisionProfile.normalize(safe["comparison"]["postProfile"], "post_execution")
        except Exception as exc:
            raise ValueError("invalid post profile") from exc
        _validate_confidence(safe["comparison"]["confidence"])
        if eventual["role"] is not None and not isinstance(eventual["role"], str) or not isinstance(eventual["result"], (dict, str)) or eventual["gates"] is not None and not isinstance(eventual["gates"], (dict, list)) or eventual["model"] is not None and not isinstance(eventual["model"], str) or eventual["usage"] is not None and not isinstance(eventual["usage"], dict):
            raise ValueError("invalid eventual comparison types")
        if eventual["usage"] is not None:
            _validate_usage(eventual["usage"])
        if not isinstance(safe["comparison"]["authoritativePreDecision"], dict) or not isinstance(safe["comparison"]["mismatches"], list) or any(not isinstance(x, dict) for x in safe["comparison"]["mismatches"]):
            raise ValueError("invalid post comparison structures")
        _validate_usage(safe["usage"])
        if not isinstance(safe["orphanedPreObservation"], bool):
            raise ValueError("orphanedPreObservation must be boolean")
    if "correlationId" in safe and (not isinstance(safe["correlationId"], str) or len(safe["correlationId"]) != 20):
        raise ValueError("invalid correlationId")
    return safe


def _validate_confidence(confidence: Any) -> None:
    if not isinstance(confidence, dict) or set(confidence) != {"min", "mean", "perAnswer"}:
        raise ValueError("invalid confidence summary shape")
    if any(isinstance(confidence[k], bool) or not isinstance(confidence[k], (int, float)) or not 0 <= confidence[k] <= 1 for k in ("min", "mean")):
        raise ValueError("confidence summary values must be in 0..1")
    if not isinstance(confidence["perAnswer"], list) or not confidence["perAnswer"] or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in confidence["perAnswer"]):
        raise ValueError("invalid per-answer confidence")


def _validate_usage(usage: Any) -> None:
    if not isinstance(usage, dict) or set(usage) != _USAGE_KEYS or any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0) for v in usage.values()):
        raise ValueError("invalid usage shape")


def _safe_reason_code(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000 and not state_tool.contains_credential(value)


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class DecisionAudit:
    def __init__(self, root: Path | str = ".", audit_path: Path | str | None = None) -> None:
        self.root = Path(root)
        self.observations = self.root / ".agent-managed/runtime/decision-observations"
        self.audit_path = self.root / audit_path if audit_path is not None else self.root / ".agent-managed/runtime/decision-audit.jsonl"

    def record_pre(self, observation: dict[str, Any]) -> str:
        safe = _validate_phase(observation, "pre_execution")
        correlation = hashlib.sha256(_canonical(safe).encode()).hexdigest()[:20]
        safe.update({"schemaVersion": 1, "kind": "DecisionShadowObservation", "phase": "pre_execution", "correlationId": correlation})
        try:
            self.observations.mkdir(parents=True, exist_ok=True)
            temp = self.observations / f".{correlation}.tmp"
            self._append(safe)
            temp.write_text(_canonical(safe) + "\n", encoding="utf-8")
            os.replace(temp, self.observations / f"{correlation}.json")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            try:
                temp.unlink()
            except (OSError, UnboundLocalError):
                pass
        return correlation

    def record_post(self, comparison: dict[str, Any]) -> None:
        try:
            if not isinstance(comparison, dict):
                raise ValueError("post record must be an object")
            correlation = comparison.get("correlationId")
            if not isinstance(correlation, str):
                correlation = hashlib.sha256(_canonical(comparison).encode()).hexdigest()[:20]
                comparison = {**comparison, "correlationId": correlation}
            orphaned = not (self.observations / f"{correlation}.json").is_file()
            safe = dict(comparison)
            safe["orphanedPreObservation"] = orphaned
            safe = _validate_phase(safe, "post_execution")
            safe.update({"schemaVersion": 1, "kind": "DecisionShadowObservation", "phase": "post_execution", "orphanedPreObservation": orphaned})
            self._append(safe)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return

    def _append(self, record: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(_canonical(record) + "\n")
