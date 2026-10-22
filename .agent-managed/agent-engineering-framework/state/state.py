#!/usr/bin/env python3
"""Portable state utility for the Agent Engineering Framework.

State: .specs/features/<feature>/state.json

Commands:
  state.py new <feature>
  state.py get <feature> [--json]
  state.py set <feature> <dotted-key> <json-or-string-value>
  state.py update <feature> <dotted-key> <json-or-string-value>
  state.py mark <feature> <task> <status>
  state.py gate <feature> <gate> <PASS|FAIL|SKIP|EXTERNAL> [--command <command>] [--evidence <compact-output>]
  state.py gate-decision <feature> <task> <gate-kind> --command <command> --scope <path> [--scope <path>]
  state.py developer-close <feature> <task> --require <gate-kind,...> --scope <path> [--scope <path>]
  state.py review-start <feature> <task>
  state.py review-result <feature> <task> <PASS|CHANGES_REQUESTED> --findings <json-array>
  state.py gate <feature> <gate> <PASS|FAIL|SKIP> [<command> <compact-output>]
  state.py handoff <feature> <json-object>
  state.py migrate <feature>
  state.py validate <feature>
  state.py close <feature>
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import os
import re
import sys
import fcntl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEATURE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TASK_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# Projects may keep an established compact task sequence (T1, T2, …) or use
# zero-padded IDs (T001, T002, …). Both are portable identifiers.
WORK_ITEM_RE = re.compile(r"^(?:T\d{1,3}|FIX-(?:T\d{1,3}|HARNESS)-\d{2})$")
LEGACY_TASK_STATUSES = {"pending", "in_progress", "reviewing", "passed", "failed"}
TASK_STATUSES = {
    "pending", "ready", "implementing", "gates", "reviewing", "fixing",
    "qa", "blocked", "passed", "escalated",
}
COMPLEXITIES = {"LOW", "MEDIUM", "HIGH"}
RISKS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
GATE_RESULTS = {"PASS", "FAIL", "SKIP", "EXTERNAL"}
GATE_KINDS = {
    "format", "static-analysis", "lint", "focused-tests", "required-tests", "build",
}
GATE_ROLES = {"developer", "qa", "human"}
EXTERNAL_GATE_CLASSIFICATIONS = {
    "EXTERNAL_DIRTY_WORKTREE", "PROVIDER_UNAVAILABLE", "TOOL_UNAVAILABLE",
    "INFRASTRUCTURE_UNAVAILABLE", "KNOWN_BASELINE",
}
REVIEW_RESULTS = {"PASS", "CHANGES_REQUESTED"}
REVIEW_SEVERITY_ALIASES = {
    "BLOCKER": "BLOCKER", "MAJOR": "MAJOR", "MINOR": "MINOR",
    "CRITICAL": "BLOCKER", "HIGH": "BLOCKER", "MEDIUM": "MAJOR", "LOW": "MINOR",
}
FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
PHASES = {
    "specify", "design", "tasks", "ready", "implementing", "gates",
    "reviewing", "fixing", "qa", "final_validation", "ready_for_pr",
    "blocked", "human_escalation",
}
HARNESSES = {"opencode", "codex", "copilot", "claude", "human", None}
FORBIDDEN_KEYS = {
    # Harness-prefixed session state (camelCase)
    "opencodeState", "codexState", "copilotState",
    "opencodeSession", "codexSession", "copilotSession",
    "opencodeThread", "codexThread", "copilotThread",
    "opencodeConversation", "codexConversation", "copilotConversation",
    "opencodeTranscript", "codexTranscript", "copilotTranscript",
    "opencodeReasoningLog", "codexReasoningLog", "copilotReasoningLog",
    "opencodeHarnessState", "codexHarnessState", "copilotHarnessState",
    # Generic session authority (camelCase)
    "session", "sessionId", "thread", "threadId",
    "conversation", "conversationId", "transcript",
    "reasoningLog", "harnessState",
    # Chain of thought
    "chainOfThought",
    # snake_case variants
    "opencode_state", "codex_state", "copilot_state",
    "opencode_session", "codex_session", "copilot_session",
    "opencode_thread", "codex_thread", "copilot_thread",
    "opencode_conversation", "codex_conversation", "copilot_conversation",
    "opencode_transcript", "codex_transcript", "copilot_transcript",
    "opencode_reasoning_log", "codex_reasoning_log", "copilot_reasoning_log",
    "opencode_harness_state", "codex_harness_state", "copilot_harness_state",
    "session_id", "thread_id", "conversation_id",
    "reasoning_log", "harness_state",
    "chain_of_thought",
    # kebab-case variants
    "opencode-session", "codex-session", "copilot-session",
    "opencode-thread", "codex-thread", "copilot-thread",
    "opencode-conversation", "codex-conversation", "copilot-conversation",
    "opencode-transcript", "codex-transcript", "copilot-transcript",
    "opencode-reasoning-log", "codex-reasoning-log", "copilot-reasoning-log",
    "opencode-harness-state", "codex-harness-state", "copilot-harness-state",
    "session-id", "thread-id", "conversation-id",
    "reasoning-log", "harness-state",
    "chain-of-thought",
}
REQUIRED_KEYS = {
    "schemaVersion", "feature", "created", "updated", "phase",
    "currentTask", "reviewIteration", "lastHarness", "lastAgent",
    "lastModel", "lastResult", "blocker", "attempts", "tasks", "gates",
    "handoff", "metrics",
}
V2_REQUIRED_KEYS = REQUIRED_KEYS | {
    "readyTasks", "runningTasks", "blockedTasks", "parallelTasks",
    "executionPolicy", "revision",
}
SENSITIVE_MEMORY_KEY = re.compile(
    r"prompt|transcript|conversation|session|thread|reasoning|chain.?of.?thought|secret|credential|password|passwd|pwd|api.?key|access.?token|refresh.?token|auth.?token",
    re.IGNORECASE,
)
CREDENTIAL_VALUE = re.compile(
    r"BEGIN [A-Z ]*PRIVATE KEY"
    r"|Authorization\s*:\s*Token\s+\S+"
    r"|Bearer\s+\S+"
    r"|(?:api.?key|access.?token|refresh.?token|auth.?token|client.?secret|oauth.?secret|password|passwd|pwd|token)\s*[:=]\s*\S+"
    r"|(?:password|passwd|pwd)\s+\S+"
    r"|\bsk-[A-Za-z0-9_-]{8,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{8,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{12,}\b"
    r"|\bya29\.[A-Za-z0-9_-]{8,}\b"
    r"|\bxox[a-z]-[A-Za-z0-9-]{12,}\b"
    r"|\bglpat-[A-Za-z0-9_-]{12,}\b"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b",
    re.IGNORECASE,
)
BASIC_CREDENTIAL = re.compile(r"\bBasic\s+(\S+)", re.IGNORECASE)
BASIC_TOKEN = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
HANDOFF_KEYS = {"task", "reqs", "ads", "status", "next", "blocker", "evidence", "options", "files", "base", "head", "gate", "commit"}


def default_convergence() -> dict[str, Any]:
    return {
        "developerClosure": None,
        "gateLedger": {},
        "noProgressRounds": 0,
        "lastStop": None,
        "reviewFindings": [],
    }


def default_task_state() -> dict[str, Any]:
    return {
        "status": "pending",
        "complexity": "MEDIUM",
        "risk": "MEDIUM",
        "agent": None,
        "modelClass": None,
        "parallelEligible": False,
        "reviewIteration": 0,
        "reclassificationReason": None,
        "reclassificationReasons": {},
        "convergence": default_convergence(),
    }


def repository_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".specs").is_dir():
            return candidate
    return current


def feature_dir(feature: str) -> Path:
    if not FEATURE_RE.fullmatch(feature) or ".." in feature:
        fail(f"invalid feature id: {feature}")
    return repository_root() / ".specs" / "features" / feature


def state_path(feature: str) -> Path:
    return feature_dir(feature) / "state.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def default_state(feature: str) -> dict[str, Any]:
    timestamp = now()
    return {
        "schemaVersion": 2,
        "revision": 0,
        "feature": feature,
        "created": timestamp,
        "updated": timestamp,
        "phase": "specify",
        "currentTask": None,
        "reviewIteration": 0,
        "lastHarness": None,
        "lastAgent": None,
        "lastModel": None,
        "lastResult": None,
        "blocker": None,
        "attempts": {},
        "tasks": {},
        "readyTasks": [],
        "runningTasks": [],
        "blockedTasks": [],
        "parallelTasks": [],
        "executionPolicy": {
            "mode": "BALANCED",
            "maxReviewIterations": 2,
            "maxSameGateFailure": 2,
            "maxNoProgressRounds": 1,
            "maxParallelAgents": 3,
            "preferCostEfficientModels": True,
        },
        "gates": {},
        "handoff": None,
        "metrics": {"tasks": {}, "feature": {}},
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def load(feature: str) -> dict[str, Any]:
    path = state_path(feature)
    if not path.exists():
        fail(f"no state for feature {feature!r} (run: state.py new {feature})")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"invalid state file {path}: {error}")
    if not isinstance(state, dict):
        fail(f"invalid state file {path}: root must be object")
    return state


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_scope(values: list[str]) -> list[str]:
    if not values:
        fail("convergence gate requires at least one --scope path")
    root = repository_root().resolve()
    normalized: list[str] = []
    for raw in values:
        candidate = Path(raw)
        if candidate.is_absolute() or not raw.strip() or ".." in candidate.parts:
            fail(f"invalid scope path: {raw!r}")
        target = (root / candidate).resolve()
        if not target.is_relative_to(root):
            fail(f"scope must stay inside repository: {raw!r}")
        normalized.append(candidate.as_posix())
    return sorted(dict.fromkeys(normalized))


def source_fingerprint(scope: list[str]) -> str:
    """Hash the declared task boundary without relying on Git or a harness session."""
    root = repository_root().resolve()
    entries: list[tuple[str, str, str]] = []
    for relative in scope:
        target = root / relative
        if target.is_dir():
            paths = sorted(path for path in target.rglob("*") if path.is_file())
        else:
            paths = [target]
        for path in paths:
            display = path.relative_to(root).as_posix()
            if not path.exists():
                entries.append((display, "missing", ""))
            else:
                entries.append((display, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return canonical_fingerprint(entries)


def task_record(state: dict[str, Any], task: str) -> dict[str, Any]:
    if not WORK_ITEM_RE.fullmatch(task):
        fail(f"invalid task id: {task}")
    record = state.setdefault("tasks", {}).get(task)
    if not isinstance(record, dict):
        fail(f"unknown v2 task: {task}")
    convergence = record.get("convergence")
    if convergence is None:
        convergence = default_convergence()
        record["convergence"] = convergence
    if not isinstance(convergence, dict):
        fail(f"invalid convergence state for {task}")
    return record


def convergence_record(task: dict[str, Any]) -> dict[str, Any]:
    value = task.setdefault("convergence", default_convergence())
    if not isinstance(value, dict):
        fail("task convergence must be object")
    return value


def update_task_collections(state: dict[str, Any], task_id: str) -> None:
    for key in ("readyTasks", "runningTasks", "blockedTasks", "parallelTasks"):
        state[key] = [value for value in state.get(key, []) if value != task_id]
    task = state["tasks"].get(task_id)
    status = task.get("status") if isinstance(task, dict) else None
    if status == "ready":
        state["readyTasks"].append(task_id)
    elif status in {"implementing", "gates", "reviewing", "fixing", "qa"}:
        state["runningTasks"].append(task_id)
    elif status == "blocked":
        state["blockedTasks"].append(task_id)


def increment_metric(state: dict[str, Any], task: str, name: str, amount: int = 1) -> None:
    metrics = state.setdefault("metrics", {"tasks": {}, "feature": {}})
    task_metrics = metrics.setdefault("tasks", {}).setdefault(task, {})
    task_metrics[name] = int(task_metrics.get(name, 0)) + amount
    feature_metrics = metrics.setdefault("feature", {})
    feature_metrics[name] = int(feature_metrics.get(name, 0)) + amount


def block_for_convergence(state: dict[str, Any], task_id: str, reason: str, *, detail: str) -> None:
    task = task_record(state, task_id)
    convergence = convergence_record(task)
    task["status"] = "blocked"
    task["blockReason"] = "convergence"
    convergence["lastStop"] = {"reason": reason, "detail": detail, "at": now()}
    state["phase"] = "human_escalation"
    state["currentTask"] = task_id
    state["blocker"] = {"kind": "convergence", "task": task_id, "reason": reason, "detail": detail}
    update_task_collections(state, task_id)


def gate_fingerprint(task: str, kind: str, command: str, scope: list[str], source: str, *, role: str | None = None) -> str:
    value: dict[str, Any] = {"task": task, "kind": kind, "command": command, "scope": scope, "source": source}
    if role is not None:
        value["role"] = role
    return canonical_fingerprint(value)


def latest_gate_for(state: dict[str, Any], task: str, kind: str, source: str) -> tuple[str, dict[str, Any]] | None:
    matches: list[tuple[str, dict[str, Any]]] = []
    for gate_id, receipt in state.get("gates", {}).items():
        if not isinstance(receipt, dict):
            continue
        if receipt.get("task") == task and receipt.get("kind") == kind and receipt.get("sourceFingerprint") == source:
            matches.append((gate_id, receipt))
    if not matches:
        return None
    return max(matches, key=lambda value: str(value[1].get("at", "")))


def normalize_findings(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        fail("review findings must be a JSON array")
    normalized: list[dict[str, str]] = []
    for finding in raw:
        if not isinstance(finding, dict):
            fail("review finding must be object")
        severity = REVIEW_SEVERITY_ALIASES.get(str(finding.get("severity", "")).upper())
        file = finding.get("file")
        issue = finding.get("issue")
        if severity is None or not isinstance(file, str) or not file.strip() or not isinstance(issue, str) or not issue.strip():
            fail("review finding requires severity, file, and issue")
        if len(file) > 300 or len(issue) > 500 or contains_credential(issue):
            fail("review finding must be compact and non-sensitive")
        normalized.append({"severity": severity, "file": file, "issue": issue})
    return normalized


def track_task_evidence(state: dict[str, Any], previous: dict[str, Any]) -> None:
    """Invalidate prior evidence on new work; completion bookkeeping stays neutral."""
    if state.get("schemaVersion") != 2 or not isinstance(state.get("tasks"), dict):
        return
    previous_tasks = previous.get("tasks", {})
    for task_id, task in state["tasks"].items():
        if not isinstance(task, dict):
            continue
        old = previous_tasks.get(task_id, {})
        if not isinstance(old, dict):
            old = {}
        changed = not old or any(task.get(key) != old.get(key) for key in ("complexity", "risk"))
        work_status = task.get("status") in {"implementing", "fixing", "escalated"}
        failure = task.get("status") == "blocked" and task.get("blockReason") != "dependency"
        reopened = (work_status or failure or (task.get("status") == "pending" and old.get("status") == "passed")) and task.get("status") != old.get("status")
        if changed or reopened:
            task["evidenceSince"] = now()
        elif "evidenceSince" in old:
            task["evidenceSince"] = old["evidenceSince"]
        else:
            task.pop("evidenceSince", None)


def review_reentry_error(state: dict[str, Any], previous: dict[str, Any]) -> str | None:
    """Reject a new review after its configured attempts are exhausted."""
    if state.get("schemaVersion") != 2 or previous.get("schemaVersion") != 2:
        return None
    execution = state.get("executionPolicy")
    if not isinstance(execution, dict):
        return None
    limit = execution.get("maxReviewIterations")
    if not isinstance(limit, int) or isinstance(limit, bool):
        return None

    def exceeds_limit(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > limit

    entering_feature_review = (
        state.get("phase") == "reviewing" and previous.get("phase") != "reviewing"
    )
    current_task = state.get("currentTask")
    current_changed = current_task != previous.get("currentTask")
    assigning_current_review = state.get("phase") == "reviewing" and current_changed
    if entering_feature_review:
        if exceeds_limit(state.get("reviewIteration")):
            return f"feature reviewIteration reached configured limit {limit}; enter human_escalation before review reset"
        if isinstance(current_task, str):
            current = state.get("tasks", {}).get(current_task, {})
            if isinstance(current, dict) and exceeds_limit(current.get("reviewIteration")):
                return f"current task {current_task} reviewIteration reached configured limit {limit}; enter human_escalation before review reset"
    elif assigning_current_review and isinstance(current_task, str):
        current = state.get("tasks", {}).get(current_task, {})
        if isinstance(current, dict) and exceeds_limit(current.get("reviewIteration")):
            return f"current task {current_task} reviewIteration reached configured limit {limit}; enter human_escalation before review reset"

    previous_tasks = previous.get("tasks", {})
    tasks = state.get("tasks", {})
    if not isinstance(previous_tasks, dict) or not isinstance(tasks, dict):
        return None
    for task_id, task in tasks.items():
        old = previous_tasks.get(task_id, {})
        if not isinstance(task, dict) or not isinstance(old, dict):
            continue
        entering_task_review = task.get("status") == "reviewing" and old.get("status") != "reviewing"
        if not entering_task_review:
            continue
        if exceeds_limit(state.get("reviewIteration")):
            return f"feature reviewIteration reached configured limit {limit}; enter human_escalation before review reset"
        if exceeds_limit(task.get("reviewIteration")):
            return f"task {task_id} reviewIteration reached configured limit {limit}; enter human_escalation before review reset"
    return None


def save(feature: str, state: dict[str, Any]) -> Path:
    path = state_path(feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            persisted = {}
            if path.exists():
                try:
                    persisted = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    fail(f"cannot compare state revision: {error}")
                if not isinstance(persisted, dict):
                    fail("persisted state root must be object")
            if state.get("schemaVersion") == 2:
                expected_revision = state.get("revision")
                if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
                    fail("v2 revision must be non-negative integer")
                if path.exists():
                    persisted_revision = persisted.get("revision")
                    revision_bootstrap = persisted_revision is None and expected_revision == 0
                    if persisted.get("schemaVersion") == 2 and not revision_bootstrap and persisted_revision != expected_revision:
                        fail(f"state revision conflict: expected {expected_revision}, found {persisted.get('revision')}; reload before write")
                review_error = review_reentry_error(state, persisted)
                if review_error:
                    fail(review_error)
                state["revision"] = expected_revision + 1
            track_task_evidence(state, persisted)
            state["updated"] = now()
            harness = os.environ.get("AGENT_FRAMEWORK_HARNESS")
            if harness in {"opencode", "codex", "copilot", "claude", "human"}:
                state["lastHarness"] = harness
            errors = validate_state(state, expected_feature=feature)
            if not errors and state.get("phase") == "ready_for_pr":
                errors.extend(completion_errors(feature, state))
            if errors:
                fail("invalid state:\n- " + "\n- ".join(errors))
            temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return path


def sensitive_memory_errors(value: Any, path: str = "state") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SENSITIVE_MEMORY_KEY.search(str(key)) or contains_credential(str(key)):
                errors.append(f"sensitive memory key forbidden: {child_path}")
            errors.extend(sensitive_memory_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(sensitive_memory_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) > 2000:
            errors.append(f"memory string too long: {path}")
        if contains_credential(value):
            errors.append(f"credential-like memory value forbidden: {path}")
    return errors


def contains_credential(value: str) -> bool:
    if CREDENTIAL_VALUE.search(value):
        return True
    for match in BASIC_CREDENTIAL.finditer(value):
        token = match.group(1)
        if not BASIC_TOKEN.fullmatch(token):
            continue
        unpadded = token.rstrip("=")
        if len(unpadded) % 4 == 1:
            continue
        padded = unpadded + ("=" * (-len(unpadded) % 4))
        if token not in {unpadded, padded}:
            continue
        try:
            decoded = base64.b64decode(padded, validate=True)
        except (binascii.Error, ValueError):
            continue
        canonical = base64.b64encode(decoded).decode("ascii")
        if token not in {canonical, canonical.rstrip("=")}:
            continue
        if b":" in decoded:
            return True
    return False


def validate_compact_metrics(metrics: Any) -> list[str]:
    if not isinstance(metrics, dict):
        return ["metrics must be object"]
    errors: list[str] = []
    if set(metrics) - {"tasks", "feature"}:
        errors.append("v2 metrics keys must be tasks and feature only")
    for key in ("tasks", "feature"):
        if not isinstance(metrics.get(key), dict):
            errors.append(f"metrics.{key} must be object")
    for counter, value in (metrics.get("feature", {}).items() if isinstance(metrics.get("feature"), dict) else ()):
        if not isinstance(counter, str) or SENSITIVE_MEMORY_KEY.search(counter) or not isinstance(value, (int, float, bool)):
            errors.append(f"invalid feature metric counter: {counter}")
    for task, counters in (metrics.get("tasks", {}).items() if isinstance(metrics.get("tasks"), dict) else ()):
        if not isinstance(task, str) or not WORK_ITEM_RE.fullmatch(task) or not isinstance(counters, dict):
            errors.append(f"invalid task metrics entry: {task}")
            continue
        for counter, value in counters.items():
            if not isinstance(counter, str) or SENSITIVE_MEMORY_KEY.search(counter) or not isinstance(value, (int, float, bool)):
                errors.append(f"invalid task metric counter: {task}.{counter}")
    return errors


def validate_state(state: dict[str, Any], expected_feature: str | None = None) -> list[str]:
    errors: list[str] = []
    version = state.get("schemaVersion")
    required_keys = V2_REQUIRED_KEYS if version == 2 else REQUIRED_KEYS
    missing = sorted(required_keys - state.keys())
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    forbidden = sorted(FORBIDDEN_KEYS & state.keys())
    if forbidden:
        errors.append("harness/session-dependent keys forbidden: " + ", ".join(forbidden))
    if version not in {1, 2}:
        errors.append("schemaVersion must be 1 or 2")
    feature = state.get("feature")
    if not isinstance(feature, str) or not FEATURE_RE.fullmatch(feature) or ".." in feature:
        errors.append("feature must be a valid portable id")
    if expected_feature is not None and feature != expected_feature:
        errors.append(f"feature mismatch: expected {expected_feature!r}, got {feature!r}")
    if state.get("phase") not in PHASES:
        errors.append(f"invalid phase: {state.get('phase')!r}")
    current_task = state.get("currentTask")
    if current_task is not None and (not isinstance(current_task, str) or not WORK_ITEM_RE.fullmatch(current_task)):
        errors.append("currentTask must be null or a valid task id")
    iteration = state.get("reviewIteration")
    if not isinstance(iteration, int) or isinstance(iteration, bool) or not 0 <= iteration <= 3:
        errors.append("reviewIteration must be integer 0..3")
    if state.get("lastHarness") not in HARNESSES:
        errors.append("lastHarness must be opencode, codex, copilot, claude, human, or null")
    if state.get("phase") in {"final_validation", "ready_for_pr", "qa", "reviewing"} and state.get("lastHarness") is None:
        errors.append("ready_for_pr/final_validation must have lastHarness set")
    for key in ("lastAgent", "lastModel", "lastResult"):
        if state.get(key) is not None and not isinstance(state.get(key), str):
            errors.append(f"{key} must be string or null")
    if not isinstance(state.get("attempts"), dict):
        errors.append("attempts must be object")
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        errors.append("tasks must be object")
    else:
        for task, task_state in tasks.items():
            if not isinstance(task, str) or not WORK_ITEM_RE.fullmatch(task):
                errors.append(f"invalid task id: {task!r}")
            if version == 1:
                if task_state not in LEGACY_TASK_STATUSES:
                    errors.append(f"invalid legacy task status for {task}: {task_state!r}")
                continue
            if not isinstance(task_state, dict):
                errors.append(f"v2 task state for {task} must be object")
                continue
            task_required = {
                "status", "complexity", "risk", "agent", "modelClass",
                "parallelEligible", "reviewIteration", "reclassificationReason",
            }
            task_missing = sorted(task_required - task_state.keys())
            if task_missing:
                errors.append(f"v2 task {task} missing keys: {', '.join(task_missing)}")
            if "evidenceSince" in task_state and evidence_time(task_state["evidenceSince"]) is None:
                errors.append(f"invalid evidenceSince for {task}")
            reasons = task_state.get("reclassificationReasons", {})
            if not isinstance(reasons, dict) or any(
                field not in {"complexity", "risk"} or not isinstance(reason, str) or not reason.strip()
                for field, reason in reasons.items()
            ):
                errors.append(f"invalid reclassificationReasons for {task}")
            if task_state.get("blockReason") not in {None, "dependency", "operational", "classification", "convergence"}:
                errors.append(f"invalid blockReason for {task}")
            if task_state.get("status") not in TASK_STATUSES:
                errors.append(f"invalid task status for {task}: {task_state.get('status')!r}")
            if task_state.get("complexity") not in COMPLEXITIES:
                errors.append(f"invalid task complexity for {task}: {task_state.get('complexity')!r}")
            if task_state.get("risk") not in RISKS:
                errors.append(f"invalid task risk for {task}: {task_state.get('risk')!r}")
            for key in ("agent", "modelClass", "reclassificationReason"):
                if task_state.get(key) is not None and not isinstance(task_state.get(key), str):
                    errors.append(f"v2 task {task} {key} must be string or null")
            if not isinstance(task_state.get("parallelEligible"), bool):
                errors.append(f"v2 task {task} parallelEligible must be boolean")
            task_iteration = task_state.get("reviewIteration")
            if not isinstance(task_iteration, int) or isinstance(task_iteration, bool) or not 0 <= task_iteration <= 3:
                errors.append(f"v2 task {task} reviewIteration must be integer 0..3")
            convergence = task_state.get("convergence")
            if convergence is not None:
                if not isinstance(convergence, dict):
                    errors.append(f"v2 task {task} convergence must be object")
                else:
                    allowed = {"developerClosure", "gateLedger", "noProgressRounds", "lastStop", "reviewFindings"}
                    unknown = sorted(set(convergence) - allowed)
                    if unknown:
                        errors.append(f"v2 task {task} convergence unknown keys: {', '.join(unknown)}")
                    closure = convergence.get("developerClosure")
                    if closure is not None and (
                        not isinstance(closure, dict)
                        or closure.get("status") != "VERIFIED"
                        or not FINGERPRINT_RE.fullmatch(str(closure.get("sourceFingerprint", "")))
                        or not isinstance(closure.get("requiredGates"), list)
                        or not isinstance(closure.get("gateIds"), list)
                        or not isinstance(closure.get("scope"), list)
                    ):
                        errors.append(f"invalid developerClosure for {task}")
                    ledger = convergence.get("gateLedger")
                    if not isinstance(ledger, dict):
                        errors.append(f"v2 task {task} gateLedger must be object")
                    elif any(
                        not FINGERPRINT_RE.fullmatch(key) or not isinstance(value, dict)
                        or value.get("result") not in GATE_RESULTS
                        for key, value in ledger.items()
                    ):
                        errors.append(f"invalid gateLedger for {task}")
                    no_progress = convergence.get("noProgressRounds")
                    if not isinstance(no_progress, int) or isinstance(no_progress, bool) or no_progress < 0:
                        errors.append(f"invalid noProgressRounds for {task}")
                    findings = convergence.get("reviewFindings")
                    if not isinstance(findings, list):
                        errors.append(f"invalid reviewFindings for {task}")
                    if task_state.get("status") == "reviewing" and not isinstance(closure, dict):
                        errors.append(f"reviewing task {task} requires Developer Closure")
    if version == 2:
        unknown_keys = sorted(state.keys() - V2_REQUIRED_KEYS)
        if unknown_keys:
            errors.append("v2 unknown root keys: " + ", ".join(unknown_keys))
        revision = state.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            errors.append("v2 revision must be non-negative integer")
        task_ids = set(tasks) if isinstance(tasks, dict) else set()
        execution_sets: dict[str, set[str]] = {}
        for key in ("readyTasks", "runningTasks", "blockedTasks", "parallelTasks"):
            values = state.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                errors.append(f"{key} must be array of task ids")
                continue
            execution_sets[key] = set(values)
            if len(values) != len(set(values)):
                errors.append(f"{key} must not contain duplicates")
            unknown = sorted(set(values) - task_ids)
            if unknown:
                errors.append(f"{key} contains unknown tasks: {', '.join(unknown)}")
        ready = execution_sets.get("readyTasks", set())
        running = execution_sets.get("runningTasks", set())
        blocked = execution_sets.get("blockedTasks", set())
        parallel = execution_sets.get("parallelTasks", set())
        if (ready & running) or (ready & blocked) or (running & blocked):
            errors.append("readyTasks, runningTasks, and blockedTasks must be disjoint")
        if not parallel <= ready:
            errors.append("parallelTasks must be subset of readyTasks")
        if isinstance(tasks, dict):
            running_statuses = {"implementing", "gates", "reviewing", "fixing", "qa"}
            for task_id, task_state in tasks.items():
                if not isinstance(task_state, dict):
                    continue
                status = task_state.get("status")
                if status == "ready" and task_id not in ready:
                    errors.append(f"ready task missing from readyTasks: {task_id}")
                if status in running_statuses and task_id not in running:
                    errors.append(f"running task missing from runningTasks: {task_id}")
                if status == "blocked" and task_id not in blocked:
                    errors.append(f"blocked task missing from blockedTasks: {task_id}")
                if task_id in parallel and task_state.get("parallelEligible") is not True:
                    errors.append(f"parallel task is not eligible: {task_id}")
            for task_id in ready:
                if not isinstance(tasks.get(task_id), dict) or tasks[task_id].get("status") != "ready":
                    errors.append(f"readyTasks contains non-ready task: {task_id}")
            for task_id in running:
                if not isinstance(tasks.get(task_id), dict) or tasks[task_id].get("status") not in running_statuses:
                    errors.append(f"runningTasks contains non-running task: {task_id}")
            for task_id in blocked:
                if not isinstance(tasks.get(task_id), dict) or tasks[task_id].get("status") != "blocked":
                    errors.append(f"blockedTasks contains non-blocked task: {task_id}")
        execution = state.get("executionPolicy")
        if not isinstance(execution, dict):
            errors.append("executionPolicy must be object")
        else:
            if execution.get("mode") not in {"ECONOMY", "BALANCED", "QUALITY"}:
                errors.append("executionPolicy.mode must be ECONOMY, BALANCED, or QUALITY")
            for key in ("maxReviewIterations", "maxSameGateFailure", "maxNoProgressRounds", "maxParallelAgents"):
                value = execution.get(key)
                maximum = 3 if key != "maxParallelAgents" else 10
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                    errors.append(f"executionPolicy.{key} must be integer 1..{maximum}")
            review_limit = execution.get("maxReviewIterations")
            if isinstance(review_limit, int) and not isinstance(review_limit, bool) and 1 <= review_limit <= 3:
                if isinstance(iteration, int) and iteration > review_limit:
                    errors.append("reviewIteration exceeds executionPolicy.maxReviewIterations")
                if isinstance(tasks, dict):
                    for task_id, task_state in tasks.items():
                        if isinstance(task_state, dict) and isinstance(task_state.get("reviewIteration"), int) and task_state["reviewIteration"] > review_limit:
                            errors.append(f"task {task_id} reviewIteration exceeds executionPolicy.maxReviewIterations")
            if not isinstance(execution.get("preferCostEfficientModels"), bool):
                errors.append("executionPolicy.preferCostEfficientModels must be boolean")
            if isinstance(state.get("runningTasks"), list) and isinstance(execution.get("maxParallelAgents"), int) and len(state["runningTasks"]) > execution["maxParallelAgents"]:
                errors.append("runningTasks exceeds executionPolicy.maxParallelAgents")
        handoff = state.get("handoff")
        if isinstance(handoff, dict):
            unknown_handoff = sorted(set(handoff) - HANDOFF_KEYS)
            if unknown_handoff:
                errors.append("v2 handoff unknown keys: " + ", ".join(unknown_handoff))
        errors.extend(validate_compact_metrics(state.get("metrics")))
    errors.extend(sensitive_memory_errors(state))
    gates = state.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates must be object")
    else:
        for gate, evidence in gates.items():
            if not isinstance(gate, str) or not TASK_RE.fullmatch(gate):
                errors.append(f"invalid gate id: {gate!r}")
            if not isinstance(evidence, dict):
                errors.append(f"invalid gate evidence for {gate}")
                continue
            if evidence.get("result") not in GATE_RESULTS:
                errors.append(f"invalid gate result for {gate}: {evidence.get('result')!r}")
            if evidence.get("result") == "EXTERNAL" and evidence.get("classification") not in EXTERNAL_GATE_CLASSIFICATIONS:
                errors.append(f"external gate {gate} requires supported classification")
            for key in ("sourceFingerprint", "gateFingerprint", "failureSignature"):
                if key in evidence and not FINGERPRINT_RE.fullmatch(str(evidence.get(key, ""))):
                    errors.append(f"invalid {key} for gate {gate}")
            for key in ("at", "command", "evidence"):
                if not isinstance(evidence.get(key), str) or not evidence[key].strip():
                    errors.append(f"gate {gate} must include non-empty {key}")
    if version == 1 and not isinstance(state.get("metrics"), dict):
        errors.append("metrics must be object")
    if not isinstance(state.get("created"), str) or not isinstance(state.get("updated"), str):
        errors.append("created and updated must be strings")
    return errors


def evidence_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def completion_errors(feature: str, state: dict[str, Any]) -> list[str]:
    """Structural closure guard, not proof of evidence authorship or authenticity."""
    routing = None
    routing_module = os.environ.get("AGENT_FRAMEWORK_ROUTING_MODULE")
    if routing_module:
        try:
            routing = importlib.import_module(routing_module)
        except ImportError as error:
            return [f"cannot load configured state routing extension: {error}"]

    errors: list[str] = []
    directory = feature_dir(feature)
    tasks = state.get("tasks", {})
    if not tasks or any((value.get("status") if isinstance(value, dict) else value) != "passed" for value in tasks.values()):
        errors.append("ready_for_pr requires every task passed and at least one task")
    if state.get("blocker") is not None:
        errors.append("ready_for_pr requires blocker exactly null")
    for key in ("readyTasks", "runningTasks", "blockedTasks", "parallelTasks"):
        if state.get(key):
            errors.append(f"ready_for_pr requires empty {key}")
    task_records = [value for value in tasks.values() if isinstance(value, dict)] if isinstance(tasks, dict) else []
    for task_id, task in ((task_id, value) for task_id, value in tasks.items() if isinstance(value, dict)):
        if "convergence" in task and not isinstance(task.get("convergence", {}).get("developerClosure"), dict):
            errors.append(f"ready_for_pr requires Developer Closure for {task_id}")
    verification_declared = any(isinstance(value.get("requiredVerification"), list) for value in task_records)
    if verification_declared:
        all_verification = {
            item for value in task_records for item in value.get("requiredVerification", [])
            if isinstance(item, str)
        }
        required_gate_names = ["protocol", "reviewer"]
        if "full-gates" in all_verification:
            required_gate_names.insert(0, "full")
        if any(value.get("qaRequired") is True for value in task_records) or any(item.startswith("qa-") for item in all_verification):
            required_gate_names.append("qa")
    else:
        # Older V2 state has no per-task verification projection. Keep its
        # stricter closure contract until it is explicitly migrated/synced.
        required_gate_names = ["full", "protocol", "reviewer", "qa"]
    if routing is not None:
        try:
            text = (directory / "tasks.md").read_text(encoding="utf-8")
            definitions, execution = routing.parse_tasks(directory / "tasks.md")
            errors.extend(routing.validate_definitions(definitions, execution, routing.load_policy()))
            headers = list(routing.TASK_HEADER.finditer(text))
            if len(headers) != len(definitions):
                errors.append("tasks.md contains duplicate task IDs")
            if set(definitions) != set(tasks):
                errors.append("tasks.md task IDs must exactly match state tasks")
            for index, header in enumerate(headers):
                end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
                fields = [(name.strip().lower(), value.strip()) for name, value in routing.FIELD.findall(text[header.end():end])]
                statuses = [value.lower() for name, value in fields if name == "status"]
                if statuses != ["passed"]:
                    errors.append(f"tasks.md {header.group(1)} must have one Status: Passed")
        except (OSError, ValueError) as error:
            errors.append(f"cannot validate tasks.md for closure: {error}")

    created = evidence_time(state.get("created"))
    thresholds = [created] if created else []
    thresholds.extend(stamp for value in tasks.values() if isinstance(value, dict)
                      if (stamp := evidence_time(value.get("evidenceSince"))) is not None)
    since = max(thresholds) if thresholds else None
    gate_times: list[datetime] = []
    for name in required_gate_names:
        gate = state.get("gates", {}).get(name)
        if not isinstance(gate, dict) or gate.get("result") != "PASS":
            errors.append(f"ready_for_pr requires gate {name} PASS")
            continue
        at = evidence_time(gate.get("at"))
        if at is None:
            errors.append(f"gate {name} requires timezone-aware timestamp")
        elif since is not None and at < since:
            errors.append(f"gate {name} predates current correction evidence")
        else:
            gate_times.append(at)
        for key in ("command", "evidence"):
            value = gate.get(key)
            if not isinstance(value, str) or not value.strip() or re.search(
                r"compatibility record|migrated legacy|not supplied|\b(?:TBD|TODO|placeholder|pending)\b|<[^>]+>", value, re.IGNORECASE
            ):
                errors.append(f"gate {name} requires actual {key}, not placeholder")

    if all(name in state.get("gates", {}) for name in required_gate_names):
        parsed_gate_times = {name: evidence_time(state["gates"][name].get("at"))
                             for name in required_gate_names
                             if isinstance(state["gates"].get(name), dict)}
        prerequisites = [parsed_gate_times[name] for name in ("full", "protocol") if name in parsed_gate_times]
        reviewer_time = parsed_gate_times.get("reviewer")
        qa_time = parsed_gate_times.get("qa")
        if prerequisites and reviewer_time and max(prerequisites) >= reviewer_time:
            errors.append("gate chronology requires full/protocol before reviewer")
        if reviewer_time and qa_time and reviewer_time >= qa_time:
            errors.append("gate chronology requires reviewer before qa")

    try:
        report = (directory / "validation.md").read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"validation.md required: {error}")
        return errors
    verdicts = re.findall(r"^\s*(?:\*\*)?Verdict(?:\*\*)?:\s*(?:\*\*)?([A-Za-z_]+)(?:\*\*)?\s*$", report, re.MULTILINE | re.IGNORECASE)
    if [value.upper() for value in verdicts] != ["PASS"]:
        errors.append("validation.md requires one Verdict: PASS")
    dates = re.findall(r"^\s*(?:\*\*)?Date(?:\*\*)?:\s*(.+?)\s*$", report, re.MULTILINE | re.IGNORECASE)
    report_time = evidence_time(dates[0]) if len(dates) == 1 else None
    if report_time is None or (gate_times and report_time < max(gate_times)) or (since and report_time < since):
        errors.append("validation.md Date must be timezone-aware and cover current gates/correction")
    citations = re.findall(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]+):(\d+)(?!\d)", report)
    if not citations:
        errors.append("validation.md requires real file:line evidence")
    root = repository_root().resolve()
    for filename, line in citations:
        path = (root / filename).resolve()
        try:
            if not path.is_relative_to(root) or path == (directory / "validation.md").resolve():
                raise ValueError("citation must reference evidence inside repository")
            lines = path.read_text(encoding="utf-8").splitlines()
            if not 1 <= int(line) <= len(lines) or not lines[int(line) - 1].strip():
                raise ValueError("citation line absent or blank")
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"invalid validation evidence {filename}:{line}: {error}")
    return errors


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def command_new(feature: str) -> None:
    path = state_path(feature)
    if path.exists():
        fail(f"state already exists: {path} (use get/set)")
    print(f"created {save(feature, default_state(feature)).relative_to(repository_root())}")


def command_get(feature: str, as_json: bool) -> None:
    state = load(feature)
    if as_json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return
    for key in ("feature", "phase", "currentTask", "reviewIteration", "lastHarness", "lastAgent", "lastModel", "lastResult", "blocker"):
        print(f"{key}: {state.get(key)}")
    for task, task_state in sorted(state.get("tasks", {}).items()):
        status = task_state.get("status") if isinstance(task_state, dict) else task_state
        print(f"task {task}: {status}")


def command_set(feature: str, key: str, raw_value: str) -> None:
    state = load(feature)
    value = parse_value(raw_value)
    parts = key.split(".")
    node: dict[str, Any] = state
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            fail(f"cannot set nested key below non-object: {part}")
        node = child
    node[parts[-1]] = value
    save(feature, state)
    print(f"set {key} = {json.dumps(value, ensure_ascii=False)}")


def command_mark(feature: str, task: str, status: str) -> None:
    if not WORK_ITEM_RE.fullmatch(task):
        fail(f"invalid task id: {task}")
    state = load(feature)
    if state.get("schemaVersion") == 1:
        if status not in LEGACY_TASK_STATUSES:
            fail(f"invalid legacy task status: {status}")
        state["tasks"][task] = status
    else:
        aliases = {"in_progress": "implementing", "failed": "blocked"}
        status = aliases.get(status, status)
        if status not in TASK_STATUSES:
            fail(f"invalid task status: {status}")
        current = state["tasks"].setdefault(task, default_task_state())
        if not isinstance(current, dict):
            fail(f"invalid v2 task state: {task}")
        current["status"] = status
        current["blockReason"] = "operational" if status == "blocked" else None
        update_task_collections(state, task)
    save(feature, state)
    print(f"task {task} = {status}")


def parse_gate_details(args: list[str]) -> tuple[str | None, str | None, dict[str, Any]]:
    command: str | None = None
    evidence: str | None = None
    positionals: list[str] = []
    details: dict[str, Any] = {"scope": []}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--command" and index + 1 < len(args):
            command = args[index + 1]
            index += 2
        elif arg == "--evidence" and index + 1 < len(args):
            evidence = args[index + 1]
            index += 2
        elif arg == "--scope" and index + 1 < len(args):
            details["scope"].append(args[index + 1])
            index += 2
        elif arg in {"--task", "--role", "--kind", "--classification"} and index + 1 < len(args):
            details[arg.removeprefix("--")] = args[index + 1]
            index += 2
        elif arg in {"--command", "--evidence", "--scope", "--task", "--role", "--kind", "--classification"}:
            fail(f"{arg} requires a value")
        else:
            positionals.append(arg)
            index += 1
    if positionals:
        if len(positionals) != 2:
            fail("gate positional details require both <command> and <compact-output>")
        if command is not None or evidence is not None:
            fail("use either --command/--evidence or positional gate details, not both")
        command, evidence = positionals
    return command, evidence, details


def compatibility_gate_command(feature: str, gate: str, result: str) -> str:
    return f"state.py gate {feature} {gate} {result}"


def compatibility_gate_evidence() -> str:
    return "compatibility record: command/evidence not supplied by caller"


def command_gate(feature: str, gate: str, result: str, details: list[str]) -> None:
    if not TASK_RE.fullmatch(gate):
        fail(f"invalid gate id: {gate}")
    result = result.upper()
    if result not in GATE_RESULTS:
        fail(f"invalid gate result: {result}")
    command, evidence, metadata = parse_gate_details(details)
    if command is None:
        command = compatibility_gate_command(feature, gate, result)
    if evidence is None:
        evidence = compatibility_gate_evidence()
    if not command.strip():
        fail("gate command must be non-empty")
    if not evidence.strip():
        fail("gate evidence must be non-empty")
    state = load(feature)
    receipt: dict[str, Any] = {
        "result": result,
        "at": now(),
        "command": command,
        "evidence": evidence,
    }
    task_id = metadata.get("task")
    if task_id is not None:
        task = task_record(state, str(task_id))
        role = str(metadata.get("role", ""))
        kind = str(metadata.get("kind", ""))
        if role not in GATE_ROLES:
            fail(f"invalid gate role: {role!r}")
        if kind not in GATE_KINDS:
            fail(f"invalid gate kind: {kind!r}")
        scope = normalized_scope(list(metadata.get("scope", [])))
        source = source_fingerprint(scope)
        fingerprint = gate_fingerprint(str(task_id), kind, command, scope, source, role=role)
        receipt.update({
            "task": task_id,
            "role": role,
            "kind": kind,
            "scope": scope,
            "sourceFingerprint": source,
            "gateFingerprint": fingerprint,
        })
        if result == "EXTERNAL":
            classification = str(metadata.get("classification", ""))
            if classification not in EXTERNAL_GATE_CLASSIFICATIONS:
                fail("EXTERNAL gate requires a supported --classification")
            receipt["classification"] = classification
        else:
            convergence = convergence_record(task)
            ledger = convergence.setdefault("gateLedger", {})
            previous = ledger.get(fingerprint)
            if result == "FAIL":
                failure = canonical_fingerprint({"command": command, "evidence": evidence})
                same_failure = (
                    isinstance(previous, dict)
                    and previous.get("result") == "FAIL"
                    and previous.get("failureSignature") == failure
                )
                failures = int(previous.get("sameFailureCount", 0)) + 1 if same_failure else 1
                receipt["failureSignature"] = failure
                ledger[fingerprint] = {
                    "result": "FAIL", "failureSignature": failure,
                    "sameFailureCount": failures, "at": receipt["at"], "gateId": gate,
                }
                if role == "developer":
                    increment_metric(state, str(task_id), "gateExecutions")
                limit = state.get("executionPolicy", {}).get("maxSameGateFailure", 2)
                if same_failure and isinstance(limit, int) and failures >= limit:
                    block_for_convergence(
                        state, str(task_id), "same_gate_failure",
                        detail=f"{kind} failed with the same signature {failures} times",
                    )
            else:
                ledger[fingerprint] = {
                    "result": result, "at": receipt["at"], "gateId": gate,
                }
                convergence["noProgressRounds"] = 0
                if role == "developer":
                    increment_metric(state, str(task_id), "gateExecutions")
    state.setdefault("gates", {})[gate] = receipt
    save(feature, state)
    print(f"gate {gate} = {result}")


def command_gate_decision(feature: str, task_id: str, kind: str, details: list[str]) -> None:
    if kind not in GATE_KINDS:
        fail(f"invalid gate kind: {kind!r}")
    command, evidence, metadata = parse_gate_details(details)
    if evidence is not None:
        fail("gate-decision does not accept --evidence")
    if command is None or not command.strip():
        fail("gate-decision requires --command")
    state = load(feature)
    task = task_record(state, task_id)
    scope = normalized_scope(list(metadata.get("scope", [])))
    source = source_fingerprint(scope)
    # Gate decisions drive Developer Closure. QA receipts remain useful evidence,
    # but never substitute for the Developer's task-local gate execution.
    fingerprint = gate_fingerprint(task_id, kind, command, scope, source, role="developer")
    entry = convergence_record(task).get("gateLedger", {}).get(fingerprint)
    decision = "RUN"
    if isinstance(entry, dict) and entry.get("result") == "PASS":
        increment_metric(state, task_id, "deduplicatedGateExecutions")
        decision = "REUSE_PASS"
    elif isinstance(entry, dict) and entry.get("result") == "FAIL":
        convergence = convergence_record(task)
        convergence["noProgressRounds"] = int(convergence.get("noProgressRounds", 0)) + 1
        limit = state.get("executionPolicy", {}).get("maxNoProgressRounds", 1)
        if isinstance(limit, int) and convergence["noProgressRounds"] >= limit:
            increment_metric(state, task_id, "noProgressStops")
            block_for_convergence(
                state, task_id, "no_progress",
                detail=f"{kind} would rerun against unchanged source after a recorded failure",
            )
            decision = "BLOCKED_NO_PROGRESS"
        else:
            decision = "NEEDS_SOURCE_CHANGE"
    save(feature, state)
    print(json.dumps({"decision": decision, "sourceFingerprint": source, "gateFingerprint": fingerprint}))


def command_developer_close(feature: str, task_id: str, details: list[str]) -> None:
    required: list[str] = []
    scope: list[str] = []
    index = 0
    while index < len(details):
        arg = details[index]
        if arg == "--require" and index + 1 < len(details):
            required.extend(value.strip().lower() for value in details[index + 1].split(",") if value.strip())
            index += 2
        elif arg == "--scope" and index + 1 < len(details):
            scope.append(details[index + 1])
            index += 2
        else:
            fail("developer-close accepts only --require and --scope")
    required = list(dict.fromkeys(required))
    if not required or any(value not in GATE_KINDS for value in required):
        fail("developer-close requires supported gate classes")
    state = load(feature)
    task = task_record(state, task_id)
    normalized = normalized_scope(scope)
    source = source_fingerprint(normalized)
    gate_ids: list[str] = []
    for kind in required:
        latest = latest_gate_for(state, task_id, kind, source)
        if latest is None:
            fail(f"developer closure missing {kind} gate for current source")
        gate_id, receipt = latest
        if receipt.get("role") != "developer" or receipt.get("result") not in {"PASS", "SKIP"}:
            fail(f"developer closure requires Developer {kind} PASS/SKIP")
        gate_ids.append(gate_id)
    convergence = convergence_record(task)
    convergence["developerClosure"] = {
        "status": "VERIFIED",
        "sourceFingerprint": source,
        "requiredGates": required,
        "gateIds": gate_ids,
        "scope": normalized,
        "knownFailures": [],
        "at": now(),
    }
    task["status"] = "gates"
    task["blockReason"] = None
    state["phase"] = "gates"
    state["currentTask"] = task_id
    state["lastHarness"] = "human"
    state["lastAgent"] = "developer"
    state["lastResult"] = "PASS"
    update_task_collections(state, task_id)
    increment_metric(state, task_id, "developerValidationRuns")
    save(feature, state)
    print(f"developer closure = VERIFIED ({task_id})")


def command_review_start(feature: str, task_id: str) -> None:
    state = load(feature)
    task = task_record(state, task_id)
    convergence = convergence_record(task)
    closure = convergence.get("developerClosure")
    if not isinstance(closure, dict) or closure.get("status") != "VERIFIED":
        fail("review requires VERIFIED developer closure")
    if source_fingerprint(list(closure.get("scope", []))) != closure.get("sourceFingerprint"):
        fail("review requires developer closure for current source")
    limit = state.get("executionPolicy", {}).get("maxReviewIterations", 2)
    if not isinstance(limit, int) or task.get("reviewIteration", 0) >= limit:
        block_for_convergence(state, task_id, "review_budget", detail="review budget exhausted before another review")
        save(feature, state)
        fail("review budget exhausted; task escalated")
    task["reviewIteration"] = int(task.get("reviewIteration", 0)) + 1
    state["reviewIteration"] = max(int(state.get("reviewIteration", 0)), task["reviewIteration"])
    task["status"] = "reviewing"
    task["blockReason"] = None
    state["phase"] = "reviewing"
    state["currentTask"] = task_id
    state["lastHarness"] = "human"
    state["lastAgent"] = "reviewer"
    update_task_collections(state, task_id)
    increment_metric(state, task_id, "reviewRounds")
    save(feature, state)
    print(f"review started: {task_id} round={task['reviewIteration']}")


def command_review_result(feature: str, task_id: str, result: str, details: list[str]) -> None:
    result = result.upper()
    if result not in REVIEW_RESULTS:
        fail(f"invalid review result: {result}")
    if len(details) != 2 or details[0] != "--findings":
        fail("review-result requires --findings <json-array>")
    findings = normalize_findings(parse_value(details[1]))
    blocking = [finding for finding in findings if finding["severity"] in {"BLOCKER", "MAJOR"}]
    if result == "PASS" and blocking:
        fail("PASS review cannot contain BLOCKER or MAJOR findings")
    if result == "CHANGES_REQUESTED" and not blocking:
        fail("CHANGES_REQUESTED requires BLOCKER or MAJOR finding")
    state = load(feature)
    task = task_record(state, task_id)
    if task.get("status") != "reviewing":
        fail("review-result requires task in reviewing status")
    convergence = convergence_record(task)
    convergence["reviewFindings"] = findings
    closure = convergence.get("developerClosure", {})
    state.setdefault("gates", {})["reviewer"] = {
        "result": "PASS" if result == "PASS" else "FAIL",
        "at": now(),
        "command": "independent reviewer batch",
        "evidence": f"round {task.get('reviewIteration')}: {len(findings)} finding(s)",
        "task": task_id,
        "role": "reviewer",
        "sourceFingerprint": closure.get("sourceFingerprint"),
    }
    if result == "PASS":
        task["status"] = "passed"
        state["phase"] = "ready"
        state["lastResult"] = "PASS"
    else:
        limit = state.get("executionPolicy", {}).get("maxReviewIterations", 2)
        if isinstance(limit, int) and task.get("reviewIteration", 0) >= limit:
            block_for_convergence(
                state, task_id, "review_budget",
                detail="BLOCKER/MAJOR findings remained at the final automatic review round",
            )
        else:
            task["status"] = "fixing"
            state["phase"] = "fixing"
            state["lastResult"] = "CHANGES_REQUESTED"
            increment_metric(state, task_id, "fixRounds")
            update_task_collections(state, task_id)
    state["lastHarness"] = "human"
    state["lastAgent"] = "reviewer"
    update_task_collections(state, task_id)
    save(feature, state)
    print(f"review {result}: {task_id}")


def command_handoff(feature: str, raw_value: str) -> None:
    value = parse_value(raw_value)
    if not isinstance(value, dict):
        fail("handoff must be a JSON object")
    unknown = sorted(set(value) - HANDOFF_KEYS)
    if unknown:
        fail("handoff contains unsupported keys: " + ", ".join(unknown))
    state = load(feature)
    state["handoff"] = value
    save(feature, state)
    print(f"handoff updated: {feature}")


def command_validate(feature: str) -> None:
    state = load(feature)
    errors = validate_state(state, expected_feature=feature)
    if not errors and state.get("phase") == "ready_for_pr":
        errors.extend(completion_errors(feature, state))
    if errors:
        fail("state validation failed:\n- " + "\n- ".join(errors))
    print(f"state valid: {state_path(feature).relative_to(repository_root())}")


def command_close(feature: str) -> None:
    state = load(feature)
    state["phase"] = "ready_for_pr"
    save(feature, state)
    print(f"feature {feature} = ready_for_pr")


def command_migrate(feature: str) -> None:
    state = load(feature)
    old_version = state.get("schemaVersion")
    defaults = default_state(feature)
    for key, value in defaults.items():
        state.setdefault(key, value)
    gates = state.get("gates")
    if isinstance(gates, dict):
        for gate, evidence in gates.items():
            if not isinstance(evidence, dict):
                continue
            result = str(evidence.get("result", "SKIP")).upper()
            if result not in GATE_RESULTS:
                result = "SKIP"
            evidence.setdefault("result", result)
            evidence.setdefault("at", now())
            evidence.setdefault("command", compatibility_gate_command(feature, gate, result))
            evidence.setdefault("evidence", "migrated legacy gate record")
    if old_version in {None, 1}:
        status_map = {
            "pending": "pending",
            "in_progress": "implementing",
            "reviewing": "reviewing",
            "passed": "passed",
            "failed": "blocked",
        }
        migrated_tasks: dict[str, Any] = {}
        for task, status in state.get("tasks", {}).items():
            migrated_tasks[task] = {
                **default_task_state(),
                "status": status_map.get(status, "blocked"),
                "reclassificationReason": "legacy metadata default",
            }
        state["tasks"] = migrated_tasks
        state["readyTasks"] = [task for task, value in migrated_tasks.items() if value["status"] == "ready"]
        state["runningTasks"] = [task for task, value in migrated_tasks.items() if value["status"] in {"implementing", "gates", "reviewing", "fixing", "qa"}]
        state["blockedTasks"] = [task for task, value in migrated_tasks.items() if value["status"] == "blocked"]
        state["parallelTasks"] = []
    elif isinstance(state.get("tasks"), dict):
        for task in state["tasks"].values():
            if isinstance(task, dict):
                task.setdefault("convergence", default_convergence())
    execution = state.get("executionPolicy")
    if isinstance(execution, dict):
        execution.setdefault("maxSameGateFailure", 2)
        execution.setdefault("maxNoProgressRounds", 1)
    state["schemaVersion"] = 2
    save(feature, state)
    print(f"state migrated: {state_path(feature).relative_to(repository_root())}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        fail(__doc__ or "")
    command = args.pop(0)
    if command == "new" and len(args) == 1:
        command_new(args[0])
    elif command == "get" and args:
        command_get(args[0], "--json" in args[1:])
    elif command in {"set", "update"} and len(args) == 3:
        command_set(args[0], args[1], args[2])
    elif command == "mark" and len(args) == 3:
        command_mark(args[0], args[1], args[2])
    elif command == "gate" and len(args) >= 3:
        command_gate(args[0], args[1], args[2], args[3:])
    elif command == "gate-decision" and len(args) >= 3:
        command_gate_decision(args[0], args[1], args[2], args[3:])
    elif command == "developer-close" and len(args) >= 2:
        command_developer_close(args[0], args[1], args[2:])
    elif command == "review-start" and len(args) == 2:
        command_review_start(args[0], args[1])
    elif command == "review-result" and len(args) >= 4:
        command_review_result(args[0], args[1], args[2], args[3:])
    elif command == "handoff" and len(args) == 2:
        command_handoff(args[0], args[1])
    elif command == "migrate" and len(args) == 1:
        command_migrate(args[0])
    elif command == "validate" and len(args) == 1:
        command_validate(args[0])
    elif command == "close" and len(args) == 1:
        command_close(args[0])
    else:
        fail(f"invalid arguments for command {command!r}\n{__doc__}")


if __name__ == "__main__":
    main()
