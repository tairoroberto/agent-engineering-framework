#!/usr/bin/env python3
"""Adaptive task routing for the Agent Engineering Framework.

Commands:
  routing.py validate <tasks.md>
  routing.py route <tasks.md> <task>
  routing.py resolve <tasks.md> <task> <codex|opencode|copilot|claude> [--provider <name>] [--exclude-model <model>]
  routing.py resolve-class <harness> <modelClasses|reviewClasses|qaClasses> <class> [--provider <name>] [--exclude-model <model>]
  routing.py sync <feature>
  routing.py reclassify <feature> <task> <complexity|risk> <value> --reason <short-reason>
  routing.py record <feature> <task> <harness> <agent> <result> [--model <id>] [--model-class <class>] [--reviews <n>] [--gate-failures <n>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
REFERENCE_DIR = FRAMEWORK_ROOT / "skills" / "engineering-protocol" / "references"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import state as state_tool  # noqa: E402

COMPLEXITIES = ("LOW", "MEDIUM", "HIGH")
RISKS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
MODEL_CLASS_ORDER = (
    "cost-efficient-coding",
    "balanced-coding",
    "strong-coding",
    "strongest-appropriate",
)
# Accept an existing project's compact T1/T34 sequence as well as T001/T034.
# The framework does not renumber project-owned task IDs during migration.
TASK_ID = r"(?:T\d{1,3}|FIX-[A-Za-z0-9_-]+)"
WORK_ITEM_RE = re.compile(r"^(?:T\d{1,3}|FIX-(?:T\d{1,3}|HARNESS)-\d{2})$")
TASK_HEADER = re.compile(rf"^###\s+({TASK_ID}):\s+(.+?)\s*$", re.MULTILINE)
FIELD = re.compile(r"^\*\*([^*]+)\*\*:\s*(.*?)\s*$", re.MULTILINE)
SAFE_REASON = re.compile(r"^[A-Za-z0-9 .,:_+/@#()-]{1,160}$")
METRIC_ALLOWED = {
    "task", "harness", "agent", "model", "modelClass", "result",
    "reviewIterations", "gateFailures", "inputTokens", "outputTokens",
    "costMicrounits", "at",
}
METRIC_AGENTS = {"orchestrator", "planner", "developer", "reviewer", "qa", "human"}
HARNESS_MAPPINGS = {
    "codex": ".codex/routing.json",
    "opencode": ".opencode/routing.json",
    "copilot": ".github/routing.json",
    "claude": ".claude/routing.json",
}
PROVIDERS = ("auto", "openai", "opencode", "openrouter", "copilot", "claude")
METRIC_FORBIDDEN = re.compile(
    r"prompt|transcript|conversation|thread|session|reasoning|chain.?of.?thought|secret|credential|api.?key|access.?token|refresh.?token|auth.?token",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    title: str
    dependencies: tuple[str, ...]
    complexity: str
    risk: str
    domains: tuple[str, ...]
    capabilities: tuple[str, ...]
    parallelizable: bool
    conflicts: tuple[str, ...]
    verification: tuple[str, ...]
    gates: tuple[str, ...]
    classification_source: str
    classification_confidence: str
    classification_reasons: tuple[str, ...]


def load_policy() -> dict[str, Any]:
    return json.loads((REFERENCE_DIR / "routing-policy.json").read_text(encoding="utf-8"))


def csv_values(raw: str) -> tuple[str, ...]:
    if not raw or raw.lower() in {"none", "n/a"}:
        return ()
    return tuple(dict.fromkeys(value.strip().lower() for value in raw.split(",") if value.strip()))


def dependency_values(raw: str) -> tuple[str, ...]:
    if not raw or raw.lower() == "none":
        return ()
    return tuple(dict.fromkeys(re.findall(rf"(?<![A-Za-z0-9_-]){TASK_ID}(?![A-Za-z0-9_-])", raw)))


def file_boundaries(raw: str) -> tuple[str, ...]:
    return tuple(f"file:{path}" for path in re.findall(r"`([^`]+)`", raw))


def infer_classification(title: str, body: str, fields: dict[str, str], defaults: dict[str, Any]) -> tuple[str, str, str, str, tuple[str, ...]]:
    explicit_complexity = fields.get("complexity")
    explicit_risk = fields.get("risk")
    if explicit_complexity and explicit_risk:
        return explicit_complexity.upper(), explicit_risk.upper(), "declared", "HIGH", ("task metadata",)
    corpus = f"{title}\n{body}".lower()
    reasons: list[str] = []
    high_complexity = ("architecture", "distributed", "concurrency", "migration", "cross-module", "multi-module", "state machine")
    low_complexity = ("documentation", "docs", "typo", "copy", "rename", "format", "color", "token", "label")
    critical_risk = ("payment", "credential", "secret", "data loss", "destructive", "production migration")
    high_risk = ("security", "authorization", "authentication", "tenant", "encryption", "rollback", "schema migration")
    medium_risk = ("database", "api", "integration", "persistence", "permission", "offline", "sync")
    complexity_signal = any(token in corpus for token in (*high_complexity, *low_complexity))
    risk_signal = any(token in corpus for token in (*critical_risk, *high_risk, *medium_risk))
    if explicit_complexity:
        complexity = explicit_complexity.upper()
        reasons.append("complexity declared")
    elif any(token in corpus for token in high_complexity):
        complexity = "HIGH"
        reasons.append("high-complexity scope signal")
    elif any(token in corpus for token in low_complexity):
        complexity = "LOW"
        reasons.append("bounded mechanical scope signal")
    else:
        complexity = str(defaults["complexity"]).upper()
        reasons.append("no high-complexity signal")
    if explicit_risk:
        risk = explicit_risk.upper()
        reasons.append("risk declared")
    elif any(token in corpus for token in critical_risk):
        risk = "CRITICAL"
        reasons.append("critical integrity signal")
    elif any(token in corpus for token in high_risk):
        risk = "HIGH"
        reasons.append("high-risk scope signal")
    elif any(token in corpus for token in medium_risk):
        risk = "MEDIUM"
        reasons.append("integration or persistence signal")
    else:
        risk = "LOW"
        reasons.append("no elevated-risk signal")
    confidence = "MEDIUM" if explicit_complexity or explicit_risk or complexity_signal or risk_signal else "LOW"
    return complexity, risk, "inferred", confidence, tuple(reasons)


def parse_execution_policy(text: str, policy: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(policy["defaults"]["executionPolicy"])
    match = re.search(r"^## Execution Policy\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.MULTILINE)
    if not match:
        return defaults
    fields = {name.strip().lower(): value.strip() for name, value in FIELD.findall(match.group(1))}
    if "mode" in fields:
        defaults["mode"] = fields["mode"].upper()
    if "max review iterations" in fields:
        defaults["maxReviewIterations"] = int(fields["max review iterations"])
    if "max same gate failure" in fields:
        defaults["maxSameGateFailure"] = int(fields["max same gate failure"])
    if "max no progress rounds" in fields:
        defaults["maxNoProgressRounds"] = int(fields["max no progress rounds"])
    if "max parallel agents" in fields:
        defaults["maxParallelAgents"] = int(fields["max parallel agents"])
    if "prefer cost efficient models" in fields:
        defaults["preferCostEfficientModels"] = fields["prefer cost efficient models"].lower() == "true"
    return defaults


def parse_tasks(path: Path, policy: dict[str, Any] | None = None) -> tuple[dict[str, TaskDefinition], dict[str, Any]]:
    policy = policy or load_policy()
    text = path.read_text(encoding="utf-8")
    headers = list(TASK_HEADER.finditer(text))
    tasks: dict[str, TaskDefinition] = {}
    defaults = policy["defaults"]
    for header in headers:
        next_section = re.search(r"^###\s+", text[header.end():], re.MULTILINE)
        end = header.end() + next_section.start() if next_section else len(text)
        body = text[header.end():end]
        fields = {name.strip().lower(): value.strip() for name, value in FIELD.findall(body)}
        task_id = header.group(1)
        complexity, risk, source, confidence, reasons = infer_classification(header.group(2), body, fields, defaults)
        parallel_raw = fields.get("parallelizable", str(defaults["parallelizable"]))
        tasks[task_id] = TaskDefinition(
            task_id=task_id,
            title=header.group(2),
            dependencies=dependency_values(fields.get("depends on", "")),
            complexity=complexity,
            risk=risk,
            domains=csv_values(fields.get("domains", ",".join(defaults["domains"]))),
            capabilities=csv_values(fields.get("capabilities", ",".join(defaults["capabilities"]))),
            parallelizable=parallel_raw.lower() in {"true", "yes", "sim"},
            conflicts=tuple(dict.fromkeys((*csv_values(fields.get("conflicts", ",".join(defaults["conflicts"]))), *file_boundaries(fields.get("where", ""))))),
            verification=csv_values(fields.get("verification", "")),
            gates=csv_values(fields.get("gates", "")),
            classification_source=source,
            classification_confidence=confidence,
            classification_reasons=reasons,
        )
    return tasks, parse_execution_policy(text, policy)


def validate_definitions(tasks: dict[str, TaskDefinition], execution: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if execution.get("mode") not in policy["budgetModes"]:
        errors.append(f"invalid budget mode: {execution.get('mode')!r}")
    for key in ("maxReviewIterations", "maxSameGateFailure", "maxNoProgressRounds", "maxParallelAgents"):
        value = execution.get(key)
        maximum = 3 if key != "maxParallelAgents" else 10
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
            errors.append(f"{key} must be integer 1..{maximum}")
    for task in tasks.values():
        if not WORK_ITEM_RE.fullmatch(task.task_id):
            errors.append(f"invalid task id: {task.task_id}")
        if task.complexity not in COMPLEXITIES:
            errors.append(f"{task.task_id}: invalid complexity {task.complexity!r}")
        if task.risk not in RISKS:
            errors.append(f"{task.task_id}: invalid risk {task.risk!r}")
        for dependency in task.dependencies:
            if dependency not in tasks:
                errors.append(f"{task.task_id}: missing dependency {dependency}")
            if dependency == task.task_id:
                errors.append(f"{task.task_id}: self dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, trail: tuple[str, ...]) -> None:
        if task_id in visiting:
            errors.append("dependency cycle: " + " -> ".join((*trail, task_id)))
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        task = tasks[task_id]
        for dependency in task.dependencies:
            if dependency in tasks:
                visit(dependency, (*trail, task_id))
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id, ())
    return list(dict.fromkeys(errors))


def max_model_class(*classes: str) -> str:
    return max(classes, key=MODEL_CLASS_ORDER.index)


def route_task(task: TaskDefinition, execution: dict[str, Any], policy: dict[str, Any], *, complexity: str | None = None, risk: str | None = None) -> dict[str, Any]:
    complexity = complexity or task.complexity
    risk = risk or task.risk
    model_class = max_model_class(
        policy["complexityModelClass"][complexity],
        policy["riskMinimumModelClass"][risk],
        *(policy["capabilityMinimumModelClass"].get(cap, MODEL_CLASS_ORDER[0]) for cap in task.capabilities),
    )
    budget = policy["budgetModes"][execution["mode"]]
    if budget["qualityUpgrade"] and model_class != MODEL_CLASS_ORDER[-1]:
        model_class = MODEL_CLASS_ORDER[MODEL_CLASS_ORDER.index(model_class) + budget["qualityUpgrade"]]
    verification = list(policy["riskVerification"][risk])
    if risk in {"HIGH", "CRITICAL"}:
        for capability in (*task.capabilities, *task.domains):
            specialist = policy["specialistReview"].get(capability)
            if specialist and specialist not in verification:
                verification.append(specialist)
    for declared in (*task.verification, *task.gates):
        normalized = {"task": "task-gates", "full": "full-gates", "fast": "fast-gates"}.get(declared, declared)
        if normalized and normalized not in verification:
            verification.append(normalized)
    return {
        "task": task.task_id,
        "class": {"complexity": complexity, "risk": risk},
        "classification": {
            "source": task.classification_source,
            "confidence": task.classification_confidence,
            "reasons": list(task.classification_reasons),
        },
        "capabilities": list(task.capabilities),
        "exec": {
            "agent": "developer",
            "modelClass": model_class,
            "parallel": task.parallelizable,
        },
        "verify": verification,
        "budgetMode": execution["mode"],
    }


def tasks_conflict(left: TaskDefinition, right: TaskDefinition) -> bool:
    if not left.parallelizable or not right.parallelizable:
        return True
    if "unknown-boundary" in left.conflicts or "unknown-boundary" in right.conflicts:
        return True
    if set(left.conflicts) & set(right.conflicts):
        return True
    if "migration" in left.capabilities and "migration" in right.capabilities:
        return True
    serial_markers = {"ordering-required", "architecture-unstable"}
    if serial_markers & (set(left.conflicts) | set(right.conflicts)):
        return True
    left_files = [value[5:] for value in left.conflicts if value.startswith("file:")]
    right_files = [value[5:] for value in right.conflicts if value.startswith("file:")]
    for left_path in left_files:
        for right_path in right_files:
            if left_path == right_path or left_path.startswith(right_path.rstrip("/") + "/") or right_path.startswith(left_path.rstrip("/") + "/"):
                return True
    critical_domains = {"database", "api", "security", "auth", "payments"}
    return bool(set(left.domains) & set(right.domains) & critical_domains)


def readiness(tasks: dict[str, TaskDefinition], statuses: dict[str, str], max_parallel: int, *, dependency_waiting: set[str] | None = None) -> dict[str, list[str]]:
    dependency_waiting = dependency_waiting or set()
    passed = {task_id for task_id, status in statuses.items() if status == "passed"}
    running_statuses = {"implementing", "gates", "reviewing", "fixing", "qa"}
    running = [task_id for task_id in tasks if statuses.get(task_id) in running_statuses]
    ready: list[str] = []
    blocked: list[str] = []
    for task_id, task in tasks.items():
        status = statuses.get(task_id, "pending")
        if status == "passed" or status in running_statuses or status == "escalated":
            continue
        if status in {"blocked", "failed"} and task_id not in dependency_waiting:
            blocked.append(task_id)
        elif all(dependency in passed for dependency in task.dependencies):
            ready.append(task_id)
        else:
            blocked.append(task_id)
    parallel: list[str] = []
    available_slots = max(0, max_parallel - len(running))
    for task_id in ready:
        if len(parallel) >= available_slots:
            break
        task = tasks[task_id]
        active_and_selected = [*running, *parallel]
        if task.parallelizable and all(not tasks_conflict(task, tasks[selected]) for selected in active_and_selected):
            parallel.append(task_id)
    return {"readyTasks": ready, "runningTasks": running, "blockedTasks": blocked, "parallelTasks": parallel}


def feature_paths(feature: str) -> tuple[Path, Path]:
    directory = state_tool.feature_dir(feature)
    return directory / "tasks.md", directory / "state.json"


def effective_classification(task: TaskDefinition, current: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    reasons = current.get("reclassificationReasons")
    if not isinstance(reasons, dict):
        reasons = {}
    reasons = {field: reason for field, reason in reasons.items()
               if field in {"complexity", "risk"} and isinstance(reason, str) and reason.strip()}
    complexity = current.get("complexity", task.complexity) if "complexity" in reasons else task.complexity
    risk = current.get("risk", task.risk) if "risk" in reasons else task.risk
    persisted_valid = (
        task.classification_source != "declared"
        and current.get("classificationSource") in {"declared", "inferred", "persisted", "override"}
        and current.get("classificationConfidence") in {"MEDIUM", "HIGH"}
        and current.get("complexity") in COMPLEXITIES
        and current.get("risk") in RISKS
    )
    if not reasons and persisted_valid:
        complexity = current["complexity"]
        risk = current["risk"]
    return complexity, risk, reasons

def command_sync(feature: str) -> dict[str, Any]:
    tasks_path, _ = feature_paths(feature)
    policy = load_policy()
    tasks, execution = parse_tasks(tasks_path, policy)
    errors = validate_definitions(tasks, execution, policy)
    if errors:
        raise SystemExit("routing validation failed:\n- " + "\n- ".join(errors))
    state = state_tool.load(feature)
    if state.get("schemaVersion") != 2:
        raise SystemExit(f"feature {feature} uses schema v1; run state.py migrate {feature}")
    task_states = state.setdefault("tasks", {})
    statuses: dict[str, str] = {}
    for task_id, task in tasks.items():
        current = task_states.get(task_id, {})
        if not isinstance(current, dict):
            current = {}
        status = current.get("status", "pending")
        complexity, risk, reasons = effective_classification(task, current)
        route = route_task(task, execution, policy, complexity=complexity, risk=risk)
        persisted = task.classification_source != "declared" and current.get("classificationConfidence") in {"MEDIUM", "HIGH"}
        effective_confidence = "HIGH" if reasons else (current.get("classificationConfidence") if persisted else task.classification_confidence)
        if current.get("blockReason") == "classification" and effective_confidence != "LOW" and status == "blocked":
            status = "pending"
        if effective_confidence == "LOW":
            status = "blocked"
        task_states[task_id] = {
            "status": status,
            "complexity": route["class"]["complexity"],
            "risk": route["class"]["risk"],
            "agent": route["exec"]["agent"],
            "modelClass": route["exec"]["modelClass"],
            "parallelEligible": task.parallelizable,
            "reviewIteration": current.get("reviewIteration", 0),
            "reclassificationReason": current.get("reclassificationReason") if reasons else None,
            "reclassificationReasons": reasons,
            "convergence": current.get("convergence", state_tool.default_convergence()),
            "requiredVerification": route["verify"],
            "qaRequired": any(value.startswith("qa-") for value in route["verify"]),
            "blockReason": "classification" if effective_confidence == "LOW" else current.get("blockReason"),
            "classificationSource": "override" if reasons else ("persisted" if persisted else task.classification_source),
            "classificationConfidence": effective_confidence,
            "classificationReasons": list(reasons.values()) if reasons else (current.get("classificationReasons", []) if persisted else list(task.classification_reasons)),
        }
        statuses[task_id] = status
    dependency_waiting = {task_id for task_id, value in task_states.items() if value.get("blockReason") == "dependency"}
    calculated = readiness(tasks, statuses, min(execution["maxParallelAgents"], 10), dependency_waiting=dependency_waiting)
    for key, value in calculated.items():
        state[key] = value
    for task_id in calculated["readyTasks"]:
        if task_states[task_id]["status"] in {"pending", "blocked"}:
            task_states[task_id]["status"] = "ready"
            task_states[task_id]["blockReason"] = None
    for task_id in calculated["blockedTasks"]:
        if task_states[task_id]["status"] in {"pending", "ready"}:
            task_states[task_id]["status"] = "blocked"
            task_states[task_id]["blockReason"] = "dependency"
    state["executionPolicy"] = execution
    state_tool.save(feature, state)
    return calculated


def command_reclassify(feature: str, task_id: str, field: str, value: str, reason: str) -> dict[str, Any]:
    if not SAFE_REASON.fullmatch(reason) or METRIC_FORBIDDEN.search(reason):
        raise SystemExit("reason must be compact, safe, and contain no session/reasoning/secret data")
    tasks_path, _ = feature_paths(feature)
    policy = load_policy()
    tasks, execution = parse_tasks(tasks_path, policy)
    if task_id not in tasks:
        raise SystemExit(f"unknown task: {task_id}")
    value = value.upper()
    allowed = COMPLEXITIES if field == "complexity" else RISKS
    if value not in allowed:
        raise SystemExit(f"invalid {field}: {value}")
    state = state_tool.load(feature)
    if state.get("schemaVersion") != 2 or not isinstance(state.get("tasks", {}).get(task_id), dict):
        raise SystemExit("state v2 task required; run migrate then routing.py sync")
    current = state["tasks"][task_id]
    before = current[field]
    current[field] = value
    reasons = current.get("reclassificationReasons")
    if not isinstance(reasons, dict):
        reasons = {}
    reasons[field] = reason
    current["reclassificationReasons"] = reasons
    current["reclassificationReason"] = reason
    route = route_task(tasks[task_id], execution, policy, complexity=current["complexity"], risk=current["risk"])
    current["modelClass"] = route["exec"]["modelClass"]
    state_tool.save(feature, state)
    return {"task": task_id, "field": field, "from": before, "to": value, "reason": reason, "route": route}


def validate_metric_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("metrics event must be object")
    unknown = set(event) - METRIC_ALLOWED
    forbidden = [key for key in event if METRIC_FORBIDDEN.search(key)]
    if unknown or forbidden:
        raise ValueError("metrics fields forbidden: " + ", ".join(sorted(unknown | set(forbidden))))
    required = {"task", "harness", "agent", "result"}
    missing = required - event.keys()
    if missing:
        raise ValueError("metrics fields missing: " + ", ".join(sorted(missing)))
    if event["harness"] not in {"opencode", "codex", "copilot", "claude", "human"}:
        raise ValueError("invalid metrics harness")
    if event.get("agent") not in METRIC_AGENTS:
        raise ValueError("invalid metrics agent")
    if not isinstance(event["task"], str) or not state_tool.WORK_ITEM_RE.fullmatch(event["task"]):
        raise ValueError("invalid metrics task")
    if event["result"] not in {"PASS", "FAIL", "DONE", "BLOCKED", "ESCALATED", "CANCELLED"}:
        raise ValueError("invalid metrics result")
    approved = approved_models(event["harness"])
    if event.get("model") is not None and not approved:
        raise ValueError("model not approved by harness mapping; omit model and record modelClass")
    for key in ("agent", "model", "modelClass", "at"):
        value = event.get(key)
        if value is not None and (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 160
            or "\n" in value
            or METRIC_FORBIDDEN.search(value)
            or state_tool.contains_credential(value)
        ):
            raise ValueError(f"invalid or sensitive metrics {key}")
    if event.get("modelClass") is None:
        raise ValueError("metrics fields missing: modelClass")
    if event.get("modelClass") is not None and event["modelClass"] not in load_policy()["modelClasses"]:
        raise ValueError("invalid metrics modelClass")
    if event.get("model") is not None and event["model"] not in approved:
        raise ValueError("model not approved by harness mapping; omit model and record modelClass")
    if event.get("model") is not None and event["model"] not in mapped_models(event["harness"], event["modelClass"]):
        raise ValueError("model does not match metrics modelClass harness mapping")
    for key in ("reviewIterations", "gateFailures", "inputTokens", "outputTokens", "costMicrounits"):
        if event.get(key) is not None and (not isinstance(event[key], int) or isinstance(event[key], bool) or event[key] < 0):
            raise ValueError(f"{key} must be non-negative integer")
    compact = {key: value for key, value in event.items() if value is not None}
    compact.setdefault("at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return compact


def approved_models(harness: str) -> set[str]:
    mapping = load_harness_mapping(harness)
    models: set[str] = set()
    for section in ("modelClasses", "reviewClasses", "qaClasses"):
        entries = mapping.get(section, {})
        if not isinstance(entries, dict):
            continue
        for value in entries.values():
            if not isinstance(value, dict):
                continue
            candidates = value.get("candidates")
            options = candidates if isinstance(candidates, list) else [value]
            for option in options:
                if isinstance(option, dict) and isinstance(option.get("model"), str):
                    models.add(option["model"])
    return models


def mapped_models(harness: str, model_class: str) -> set[str]:
    entry = load_harness_mapping(harness).get("modelClasses", {}).get(model_class, {})
    if not isinstance(entry, dict):
        return set()
    candidates = entry.get("candidates")
    options = candidates if isinstance(candidates, list) else [entry]
    return {option["model"] for option in options if isinstance(option, dict) and isinstance(option.get("model"), str)}


def mapped_model(harness: str, model_class: str) -> str | None:
    models = mapped_models(harness, model_class)
    return next(iter(models), None)


def resolve_route(
    route: dict[str, Any], harness: str, *, provider: str = "auto",
    excluded_models: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve a portable model class using the consumer's harness mapping.

    Policy intentionally selects only a capability class.  Model identifiers and
    native agent names stay in the consumer-owned harness adapter, so an
    unavailable model is a visible configuration error instead of a fallback.
    """
    model_class = route.get("exec", {}).get("modelClass")
    if not isinstance(model_class, str):
        raise ValueError("route has no modelClass")
    selected, fallback = resolve_mapping_class(
        harness, "modelClasses", model_class, provider=provider,
        excluded_models=excluded_models,
    )
    resolved = json.loads(json.dumps(route))
    resolved["exec"].update(selected)
    resolved["exec"]["fallback"] = fallback
    resolved["harness"] = harness
    return resolved


def resolve_mapping_class(
    harness: str, family: str, class_name: str, *, provider: str = "auto",
    excluded_models: set[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Resolve one harness-local role/model class without task semantics.

    Review and QA are not implementation tasks, but must honor the same strict
    provider and quota-fallback rules as production dispatch.
    """
    mapping = load_harness_mapping(harness)
    if family not in {"modelClasses", "reviewClasses", "qaClasses"}:
        raise ValueError(f"unsupported mapping family: {family}")
    entry = mapping.get(family, {}).get(class_name)
    if not isinstance(entry, dict):
        raise ValueError(f"{harness} mapping has no route for {family}.{class_name}")
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported provider: {provider}")
    candidates = entry.get("candidates")
    options = candidates if isinstance(candidates, list) else [entry]
    excluded_models = excluded_models or set()
    provider_options = [option for option in options if isinstance(option, dict) and (provider == "auto" or option.get("provider") == provider)]
    history_role = {
        "modelClasses": "developer",
        "reviewClasses": "reviewer",
        "qaClasses": "qa",
    }[family]
    history = metric_history(
        consumer_root(), harness,
        class_name if family == "modelClasses" else None,
        role=history_role,
    )
    ranked = sorted(
        enumerate(provider_options),
        key=lambda pair: candidate_rank(pair[1], history, pair[0]),
    )
    selected = next((option for _index, option in ranked if option.get("model") not in excluded_models), None)
    if selected is None:
        detail = f" provider={provider}" if provider != "auto" else ""
        raise ValueError(f"{harness} has no available configured candidate for {family}.{class_name}{detail}")
    agent = selected.get("agent")
    if not isinstance(agent, str) or not agent:
        raise ValueError(f"{harness} mapping has no agent for {family}.{class_name}")
    resolved: dict[str, Any] = {"agent": agent, "provider": selected.get("provider", harness)}
    for field in ("model", "reasoningEffort"):
        value = selected.get(field)
        if isinstance(value, str) and value:
            resolved[field] = value
    resolved.setdefault("reasoningEffort", default_reasoning_effort(family, class_name))
    model_stats = history.get(str(selected.get("model")))
    resolved["selectionBasis"] = "verified-metrics" if model_stats and model_stats["attempts"] >= 3 else "configured-order"
    return resolved, bool(excluded_models) and bool(provider_options) and selected is not provider_options[0]


def default_reasoning_effort(family: str, class_name: str) -> str:
    if family == "modelClasses" and class_name in MODEL_CLASS_ORDER:
        return ("low", "low", "medium", "medium")[MODEL_CLASS_ORDER.index(class_name)]
    if class_name in {"qa-basic", "qa-targeted"}:
        return "low"
    return "medium"


def metric_history(
    root: Path,
    harness: str,
    model_class: str | None,
    *,
    role: str | None = None,
) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    metrics_root = root / ".specs" / "features"
    receipt_path = root / ".agent-managed" / "runtime" / "dispatch-receipts.jsonl"
    sources: list[tuple[str, Path]] = []
    if receipt_path.is_file():
        sources.append(("receipt", receipt_path))
    if metrics_root.is_dir():
        sources.extend(("metric", path) for path in sorted(metrics_root.glob("*/metrics.jsonl")))
    receipt_fingerprints: set[tuple[Any, ...]] = set()
    for source, path in sources:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-300:]
        except (OSError, UnicodeError):
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("harness") != harness or not isinstance(event.get("model"), str):
                continue
            event_role = event.get("role") or event.get("agent")
            if role is not None and event_role != role:
                continue
            if model_class is not None and event.get("modelClass") != model_class:
                continue
            fingerprint = (
                event.get("at"), event.get("task"), event_role, event.get("model"),
                event.get("result"), event.get("inputTokens"), event.get("outputTokens"),
                event.get("costMicrounits"),
            )
            # Developer receipts are also projected into the legacy per-feature
            # metrics stream. Count that projection once while preserving
            # genuinely repeated dispatch receipts.
            if source == "metric" and fingerprint in receipt_fingerprints:
                continue
            if source == "receipt":
                receipt_fingerprints.add(fingerprint)
            stats = totals.setdefault(event["model"], {"attempts": 0.0, "successes": 0.0, "tokens": 0.0, "cost": 0.0, "costSamples": 0.0})
            stats["attempts"] += 1
            if event.get("result") in {"PASS", "DONE"}:
                stats["successes"] += 1
            input_tokens = event.get("inputTokens")
            output_tokens = event.get("outputTokens")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                stats["tokens"] += input_tokens + output_tokens
            cost = event.get("costMicrounits")
            if isinstance(cost, int):
                stats["cost"] += cost
                stats["costSamples"] += 1
    return totals


def candidate_rank(option: dict[str, Any], history: dict[str, dict[str, float]], configured_index: int) -> tuple[float, float, float, int]:
    stats = history.get(str(option.get("model")))
    if stats and stats["attempts"] >= 3:
        failure_rate = 1.0 - (stats["successes"] / stats["attempts"])
        if stats["costSamples"]:
            consumption = stats["cost"] / stats["costSamples"]
        else:
            consumption = stats["tokens"] / stats["attempts"] if stats["tokens"] else float("inf")
        return (0.0, failure_rate, consumption, configured_index)
    declared_cost = option.get("costMicrounits")
    if isinstance(declared_cost, int) and declared_cost >= 0:
        return (1.0, 0.0, float(declared_cost), configured_index)
    return (2.0, 0.0, float(configured_index), configured_index)


def load_harness_mapping(harness: str) -> dict[str, Any]:
    mapping_path = HARNESS_MAPPINGS.get(harness)
    if mapping_path is None:
        return {}
    root = consumer_root()
    try:
        value = json.loads((root / mapping_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def consumer_root() -> Path:
    configured = os.environ.get("AGENT_FRAMEWORK_CONSUMER_ROOT")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if (candidate / ".agent-framework.toml").is_file():
            return candidate
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agent-framework.toml").is_file():
            return candidate
    return current


def append_metric(feature: str, event: dict[str, Any]) -> Path:
    compact = validate_metric_event(event)
    path = state_tool.feature_dir(feature) / "metrics.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("tasks")
    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("tasks")
    route_parser.add_argument("task")
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("tasks")
    resolve_parser.add_argument("task")
    resolve_parser.add_argument("harness", choices=tuple(HARNESS_MAPPINGS))
    resolve_parser.add_argument("--provider", choices=PROVIDERS, default="auto")
    resolve_parser.add_argument("--exclude-model", action="append", default=[])
    resolve_class_parser = subparsers.add_parser("resolve-class")
    resolve_class_parser.add_argument("harness", choices=tuple(HARNESS_MAPPINGS))
    resolve_class_parser.add_argument("family", choices=("modelClasses", "reviewClasses", "qaClasses"))
    resolve_class_parser.add_argument("class_name")
    resolve_class_parser.add_argument("--provider", choices=PROVIDERS, default="auto")
    resolve_class_parser.add_argument("--exclude-model", action="append", default=[])
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("feature")
    reclassify_parser = subparsers.add_parser("reclassify")
    reclassify_parser.add_argument("feature")
    reclassify_parser.add_argument("task")
    reclassify_parser.add_argument("field", choices=("complexity", "risk"))
    reclassify_parser.add_argument("value")
    reclassify_parser.add_argument("--reason", required=True)
    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("feature")
    record_parser.add_argument("task")
    record_parser.add_argument("harness")
    record_parser.add_argument("agent")
    record_parser.add_argument("result")
    record_parser.add_argument("--model")
    record_parser.add_argument("--model-class", dest="model_class")
    record_parser.add_argument("--reviews", type=int)
    record_parser.add_argument("--gate-failures", type=int)
    record_parser.add_argument("--input-tokens", type=int)
    record_parser.add_argument("--output-tokens", type=int)
    record_parser.add_argument("--cost-microunits", type=int)
    args = parser.parse_args()
    policy = load_policy()
    if args.command == "resolve-class":
        try:
            execution, fallback = resolve_mapping_class(
                args.harness, args.family, args.class_name,
                provider=args.provider, excluded_models=set(args.exclude_model),
            )
        except ValueError as error:
            raise SystemExit(str(error))
        print(json.dumps({
            "harness": args.harness,
            "family": args.family,
            "class": args.class_name,
            "exec": {**execution, "fallback": fallback},
        }, indent=2))
        return
    if args.command in {"validate", "route", "resolve"}:
        tasks, execution = parse_tasks(Path(args.tasks), policy)
        errors = validate_definitions(tasks, execution, policy)
        if errors:
            raise SystemExit("routing validation failed:\n- " + "\n- ".join(errors))
        if args.command == "validate":
            print(f"routing valid: {len(tasks)} task(s); mode={execution['mode']}")
        else:
            if args.task not in tasks:
                raise SystemExit(f"unknown task: {args.task}")
            current = {}
            persisted_path = Path(args.tasks).resolve().with_name("state.json")
            if persisted_path.exists():
                persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
                if not isinstance(persisted, dict):
                    raise SystemExit("invalid adjacent state: root must be object")
                errors = state_tool.validate_state(persisted, expected_feature=persisted_path.parent.name)
                if errors:
                    raise SystemExit("invalid adjacent state:\n- " + "\n- ".join(errors))
                candidate = persisted.get("tasks", {}).get(args.task)
                if isinstance(candidate, dict):
                    current = candidate
            complexity, risk, _ = effective_classification(tasks[args.task], current)
            route = route_task(tasks[args.task], execution, policy,
                               complexity=complexity, risk=risk)
            persisted_confidence = current.get("classificationConfidence") if isinstance(current, dict) else None
            confidence = persisted_confidence if persisted_confidence in {"MEDIUM", "HIGH"} else tasks[args.task].classification_confidence
            if persisted_confidence in {"MEDIUM", "HIGH"} and tasks[args.task].classification_source != "declared":
                route["classification"] = {
                    "source": "persisted",
                    "confidence": persisted_confidence,
                    "reasons": current.get("classificationReasons", []),
                }
            if args.command == "resolve" and confidence == "LOW":
                raise SystemExit("CLASSIFICATION_REQUIRED: deterministic inference confidence is low; declare task Complexity and Risk")
            if args.command == "resolve":
                try:
                    route = resolve_route(route, args.harness, provider=args.provider,
                                          excluded_models=set(args.exclude_model))
                except ValueError as error:
                    raise SystemExit(str(error))
            print(json.dumps(route, indent=2))
    elif args.command == "sync":
        print(json.dumps(command_sync(args.feature), indent=2))
    elif args.command == "reclassify":
        print(json.dumps(command_reclassify(args.feature, args.task, args.field, args.value, args.reason), indent=2))
    elif args.command == "record":
        if not WORK_ITEM_RE.fullmatch(args.task):
            raise SystemExit(f"invalid task: {args.task}")
        path = append_metric(args.feature, {
            "task": args.task,
            "harness": args.harness,
            "agent": args.agent,
            "model": args.model,
            "modelClass": args.model_class,
            "result": args.result,
            "reviewIterations": args.reviews,
            "gateFailures": args.gate_failures,
            "inputTokens": args.input_tokens,
            "outputTokens": args.output_tokens,
            "costMicrounits": args.cost_microunits,
        })
        print(f"metric appended: {path.relative_to(state_tool.repository_root())}")


if __name__ == "__main__":
    main()
