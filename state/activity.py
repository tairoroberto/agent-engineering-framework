#!/usr/bin/env python3
"""Per-activity model proposal, approval, receipts, and usage reporting.

The durable project configuration contains availability, not activity overrides.
Proposals and plans are short-lived execution contracts bound to current inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
try:
    import tomllib
except ImportError:  # Python 3.10 compatibility
    tomllib = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import catalog, routing
    from .model_router import ModelRouter, NoCapableModel, ROLE_BUDGETS, compress_tool_output
except ImportError:
    import catalog
    import routing
    from model_router import ModelRouter, NoCapableModel, ROLE_BUDGETS, compress_tool_output
try:
    from .decision_shadow import DecisionConfig, observe_post, observe_pre
    from .decision_audit import DecisionAudit
except ImportError:
    from decision_shadow import DecisionConfig, observe_post, observe_pre
    from decision_audit import DecisionAudit


RUNTIME = Path(".agent-managed/runtime")
PROPOSALS = RUNTIME / "proposals"
PLANS = RUNTIME / "plans"
RECEIPTS = RUNTIME / "dispatch-receipts.jsonl"
CIRCUITS = RUNTIME / "circuits"
WAITS = RUNTIME / "capacity-waits"
DECISION_CORRELATIONS = RUNTIME / "decision-correlations.json"
ROLE_ORDER = ("orchestrator", "developer", "reviewer", "qa")
CLASS_ORDER = tuple(routing.MODEL_CLASS_ORDER)
TASK_HEADER_TEMPLATE = r"^###\s+{task}:"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
SAFE_RESULT = {"PASS", "FAIL", "DONE", "BLOCKED", "ESCALATED", "CANCELLED"}
AVAILABILITY_KINDS = {"quota", "rate_limit", "model_unavailable", "context_window"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label}: root must be object")
    return value


def load_project_manifest(root: Path) -> dict[str, Any]:
    """Load the canonical project manifest for calls that lack an override."""
    path = root / ".agent-framework.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if tomllib is not None:
        try:
            return tomllib.loads(text)
        except (tomllib.TOMLDecodeError, TypeError):
            return {}
    # The supported runtimes normally provide tomllib; retain a bounded
    # compatibility parser for the test/runtime Python 3.9 image.
    result: dict[str, Any] = {}
    table: dict[str, Any] = result
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            table = result
            for part in stripped[1:-1].split("."):
                table = table.setdefault(part, {})
            continue
        if "=" not in stripped:
            continue
        key, raw = (part.strip() for part in stripped.split("=", 1))
        if raw.lower() in {"true", "false"}:
            value: Any = raw.lower() == "true"
        elif raw.startswith(("[", "{")):
            try:
                value = json.loads(raw.replace("'", '"'))
            except json.JSONDecodeError:
                value = raw.strip('"')
        else:
            try:
                value = int(raw)
            except ValueError:
                value = raw.strip('"')
        table[key] = value
    return result


def _decision_correlation_key(plan: dict[str, Any]) -> str:
    return canonical_hash({"feature": plan.get("feature"), "task": plan.get("task"), "proposalId": plan.get("proposalId")})


def _decision_task_id(task_id: str | None, target: str) -> str:
    return task_id or f"intent-{canonical_hash(target)[:12]}"


def _remember_decision_correlation(root: Path, plan_context: dict[str, Any], correlation_id: str) -> None:
    values = read_json(root / DECISION_CORRELATIONS, "decision correlation lookup") if (root / DECISION_CORRELATIONS).is_file() else {}
    values[_decision_correlation_key(plan_context)] = {"correlationId": correlation_id, "snapshot": {"feature": plan_context.get("feature"), "task": plan_context.get("task"), "proposalId": plan_context.get("proposalId")}}
    safe_write_json(root / DECISION_CORRELATIONS, values)


def _find_decision_correlation(root: Path, plan: dict[str, Any]) -> str | None:
    path = root / DECISION_CORRELATIONS
    if not path.is_file():
        return None
    try:
        values = read_json(path, "decision correlation lookup")
        entry = values.get(_decision_correlation_key(plan))
        if isinstance(entry, dict) and entry.get("snapshot") == {"feature": plan.get("feature"), "task": plan.get("task"), "proposalId": plan.get("proposalId")}:
            correlation = entry.get("correlationId")
            return correlation if isinstance(correlation, str) else None
    except ValueError:
        return None
    return None


def manifest_provider_policy(manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalized project provider policy with safe legacy defaults."""
    settings = manifest.get("provider") or {}
    if not isinstance(settings, dict):
        settings = {}
    default = settings.get("default")
    allowed = settings.get("allowed")
    strict = settings.get("strict", default is not None or allowed is not None)
    return {
        "default": default if isinstance(default, str) else None,
        "allowed": list(allowed) if isinstance(allowed, list) else None,
        "strict": bool(strict),
    }


def resolve_provider_scope(manifest: dict[str, Any], requested: str | None) -> tuple[str, str | set[str]]:
    """Resolve omitted/explicit provider against the manifest policy.

    Returns (identity_provider, candidate_scope). An omitted provider uses
    the project default when configured — never silent cross-provider `auto`.
    An explicit non-auto provider is strict and must be allowed, otherwise
    PROVIDER_MISMATCH. Only `auto` (explicit, or legacy without a default)
    may span providers, and a strict allowed list still constrains it.
    """
    policy = manifest_provider_policy(manifest)
    allowed = policy["allowed"]
    if requested is not None and requested != "auto":
        if allowed is not None and requested not in allowed:
            raise ValueError(f"PROVIDER_MISMATCH: provider {requested!r} is not allowed (allowed={allowed})")
        return requested, requested
    if requested is None and policy["default"] is not None:
        default = policy["default"]
        if allowed is not None and default not in allowed:
            raise ValueError(f"PROVIDER_MISMATCH: default provider {default!r} is not allowed (allowed={allowed})")
        return default, default
    if policy["strict"] and allowed is not None:
        scope: str | set[str] = set(allowed) if len(allowed) > 1 else allowed[0]
        identity = "auto" if len(allowed) > 1 else allowed[0]
        return identity, scope
    return "auto", "auto"


def provider_match(candidate: Any, scope: str | set[str]) -> bool:
    if scope == "auto":
        return True
    if isinstance(scope, str):
        return candidate == scope
    return candidate in scope


def select_harness(manifest: dict[str, Any], requested: str | None) -> str:
    harnesses = manifest.get("harnesses", [])
    selected = requested or os.environ.get("AGENT_KIT_HARNESS")
    if selected:
        if selected not in harnesses:
            raise ValueError(f"harness {selected!r} is not enabled in the manifest")
        return selected
    if not harnesses:
        raise ValueError("manifest has no enabled harness")
    return str(harnesses[0])


def locate_task(root: Path, target: str) -> tuple[Path | None, str | None, str]:
    """Resolve a task ID or feature without reading unrelated feature content."""
    if routing.WORK_ITEM_RE.fullmatch(target):
        matches: list[tuple[Path, str]] = []
        feature_root = root / ".specs" / "features"
        if feature_root.is_dir():
            pattern = re.compile(TASK_HEADER_TEMPLATE.format(task=re.escape(target)), re.MULTILINE)
            for path in sorted(feature_root.glob("*/tasks.md")):
                try:
                    if pattern.search(path.read_text(encoding="utf-8")):
                        matches.append((path, path.parent.name))
                except (OSError, UnicodeError):
                    continue
        if len(matches) > 1:
            raise ValueError(f"task {target} is ambiguous across features")
        if matches:
            return matches[0][0], target, matches[0][1]
        raise ValueError(f"task {target} was not found under .specs/features/*/tasks.md")
    raw_feature = target.strip().strip("/")
    feature = raw_feature if SAFE_ID.fullmatch(raw_feature) and ".." not in raw_feature else f"activity-{canonical_hash(raw_feature)[:12]}"
    path = root / ".specs" / "features" / feature / "tasks.md"
    if path.is_file():
        tasks, _execution = routing.parse_tasks(path)
        unfinished = next(iter(tasks), None)
        return path, unfinished, feature
    return None, None, feature or "activity"


def load_mapping(root: Path, harness: str) -> dict[str, Any]:
    relative = routing.HARNESS_MAPPINGS[harness]
    value = read_json(root / relative, f"{harness} routing mapping")
    return value


def mapping_options(mapping: dict[str, Any], family: str, class_name: str, provider: str | set[str]) -> list[dict[str, Any]]:
    entry = mapping.get(family, {}).get(class_name)
    if not isinstance(entry, dict):
        return []
    candidates = entry.get("candidates")
    values = candidates if isinstance(candidates, list) else [entry]
    return [
        dict(value) for value in values
        if isinstance(value, dict)
        and isinstance(value.get("model"), str)
        and provider_match(value.get("provider"), provider)
    ]


def family_model_routes(mapping: dict[str, Any], family: str, provider: str | set[str]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    entries = mapping.get(family, {})
    if not isinstance(entries, dict):
        return routes
    for class_name in entries:
        for option in mapping_options(mapping, family, class_name, provider):
            routes.setdefault(str(option["model"]), option)
    return routes


def class_rank(name: str) -> int:
    try:
        return CLASS_ORDER.index(name)
    except ValueError:
        return 0


def model_class(model: dict[str, Any]) -> str:
    classes = [value for value in model.get("classes", []) if value in CLASS_ORDER]
    return max(classes, key=class_rank) if classes else catalog.classify_model(str(model.get("id", "")))


def catalog_models(lock: dict[str, Any], harness: str, provider: str | set[str]) -> list[dict[str, Any]]:
    entry = lock.get("harnesses", {}).get(harness, {})
    values = entry.get("models", []) if isinstance(entry, dict) else []
    return [
        value for value in values
        if isinstance(value, dict)
        and value.get("available", True)
        and provider_match(value.get("provider"), provider)
    ]


def role_contracts(workflow: str, route: dict[str, Any]) -> list[tuple[str, str, str]]:
    # Complexity/risk change verification and capabilities, not default cost tier.
    contracts: list[tuple[str, str, str]] = [("orchestrator", "modelClasses", "capability-first")]
    if workflow != "review":
        contracts.append(("developer", "modelClasses", "cost-first"))
    contracts.append(("reviewer", "reviewClasses", "cost-first"))
    if any(value.startswith("qa-") for value in route.get("verify", [])):
        contracts.append(("qa", "qaClasses", "cost-first"))
    return contracts


def estimate_for(root: Path, harness: str, model: str, model_class_name: str, role: str) -> dict[str, Any]:
    history = routing.metric_history(root, harness, model_class_name, role=role)
    stats = history.get(model)
    if not stats or not stats["attempts"]:
        return {"tokens": None, "costMicrounits": None, "costUnknown": True, "samples": 0}
    attempts = int(stats["attempts"])
    tokens = int(stats["tokens"] / stats["attempts"]) if stats["tokens"] else None
    cost = int(stats["cost"] / stats["costSamples"]) if stats["costSamples"] else None
    return {"tokens": tokens, "costMicrounits": cost, "costUnknown": cost is None, "samples": attempts}


def candidate_key(candidate: dict[str, Any], estimate: dict[str, Any], index: int) -> tuple[int, float, int]:
    cost = estimate.get("costMicrounits")
    tokens = estimate.get("tokens")
    if isinstance(cost, int):
        return (0, float(cost), index)
    if isinstance(tokens, int):
        return (1, float(tokens), index)
    declared = candidate.get("price")
    if isinstance(declared, dict) and isinstance(declared.get("estimatedMicrounits"), int):
        return (0, float(declared["estimatedMicrounits"]), index)
    return (2, float(index), index)


def proposal_role(
    root: Path,
    lock: dict[str, Any],
    mapping: dict[str, Any],
    harness: str,
    provider: str | set[str],
    role: str,
    family: str,
    floor: str,
    orchestrator_model: str | None,
) -> dict[str, Any]:
    models = [catalog.descriptor_from_entry(value) for value in catalog_models(lock, harness, provider)]
    mapped = family_model_routes(mapping, family, provider)
    # Per-invocation harnesses do not need a generated model-specific adapter.
    if harness == "opencode":
        models = [model for model in models if model.model_id in mapped or role == "orchestrator"]
    if orchestrator_model and role == "orchestrator":
        models = [model for model in models if model.model_id == orchestrator_model]
    router = ModelRouter(models)
    try:
        decision = router.route(role, provider if isinstance(provider, str) else "auto")
    except NoCapableModel as error:
        prefix = "ORCHESTRATOR_UNAVAILABLE: " if role == "orchestrator" else ""
        raise ValueError(prefix + str(error)) from error
    alternatives: list[dict[str, Any]] = []
    for model in models:
        eligible = model in decision.eligible
        route_entry = mapped.get(model.model_id, {})
        estimate = estimate_for(root, harness, model.model_id, model_class({"classes": []}), role)
        alternatives.append({
            "model": model.model_id,
            "provider": model.provider,
            "class": model.cost_tier.lower(),
            "costTier": model.cost_tier,
            "eligible": eligible,
            "disabledReason": None if eligible else "capability, context, or availability constraint",
            "agent": "orchestrator" if role == "orchestrator" else route_entry.get("agent", role),
            "reasoningEffort": "high" if role == "orchestrator" else "low",
            "estimate": {
                **estimate,
                "cost": model.expected_cost(decision.estimated_input_tokens, decision.estimated_output_tokens),
            },
        })
    chosen = next(value for value in alternatives if value["model"] == decision.selected.model_id)
    return {
        "role": role,
        "family": family,
        "floor": floor,
        "locked": False,
        "recommended": chosen,
        "alternatives": alternatives,
        "routing": decision.to_dict(),
        "justification": decision.rationale,
    }


def build_role_contract(
    root: Path,
    lock: dict[str, Any],
    mapping: dict[str, Any],
    harness: str,
    provider: str | set[str],
    role: str,
    family: str,
    floor: str,
    effective_floor: str,
    orchestrator_model: str | None,
) -> dict[str, Any]:
    floor_rank = class_rank(effective_floor) if family == "modelClasses" else {
        "independent-reviewer": 1,
        "specialist-review": 2,
        "qa-basic": 0,
        "qa-targeted": 1,
        "qa-adversarial": 2,
    }.get(effective_floor, 1)
    mapped = mapping_options(mapping, family, floor, provider)
    mapped_by_model = family_model_routes(mapping, family, provider)
    preferred_models = {str(item["model"]) for item in mapped}
    alternatives: list[dict[str, Any]] = []
    for index, item in enumerate(catalog_models(lock, harness, provider)):
        identifier = str(item["id"])
        candidate_class = model_class(item)
        meets_floor = class_rank(candidate_class) >= floor_rank
        dispatchable = (
            role == "orchestrator"
            or identifier in mapped_by_model
            or harness in {"codex", "copilot", "claude"}
        )
        eligible = meets_floor and dispatchable
        reason = None
        if not meets_floor:
            reason = f"below {effective_floor} floor"
        elif not dispatchable:
            reason = "no generated adapter or per-invocation route"
        estimate = estimate_for(
            root, harness, identifier,
            effective_floor if family == "modelClasses" else candidate_class,
            role,
        )
        route_entry = mapped_by_model.get(identifier, {})
        alternatives.append({
            "model": identifier,
            "provider": item.get("provider", harness),
            "class": candidate_class,
            "eligible": eligible,
            "disabledReason": reason,
            "agent": "orchestrator" if role == "orchestrator" else route_entry.get("agent", role),
            "reasoningEffort": route_entry.get("reasoningEffort") or routing.default_reasoning_effort(family, effective_floor),
            "estimate": estimate,
            "_index": index,
        })
    eligible_values = [value for value in alternatives if value["eligible"]]
    if orchestrator_model and role == "orchestrator":
        chosen = next((value for value in eligible_values if value["model"] == orchestrator_model), None)
        if chosen is None:
            raise ValueError("ORCHESTRATOR_UNAVAILABLE: configured orchestrator model is unavailable or below its floor")
    else:
        configured_models = [value for value in eligible_values if value["model"] in preferred_models]
        pool = configured_models or eligible_values
        if not pool:
            prefix = "ORCHESTRATOR_UNAVAILABLE: " if role == "orchestrator" else ""
            scope_label = provider if isinstance(provider, str) else f"one of {sorted(provider)}"
            raise ValueError(f"{prefix}no eligible {scope_label} model for {role} at {effective_floor}")
        if role == "orchestrator":
            ordered = [str(value["model"]) for value in mapped]
            chosen = min(pool, key=lambda value: ordered.index(value["model"]) if value["model"] in ordered else len(ordered))
        else:
            chosen = min(pool, key=lambda value: candidate_key(value, value["estimate"], value["_index"]))
    chosen = dict(chosen)
    chosen.pop("_index", None)
    for value in alternatives:
        value.pop("_index", None)
    return {
        "role": role,
        "family": family,
        "floor": effective_floor,
        "locked": role == "orchestrator",
        "recommended": chosen,
        "alternatives": alternatives,
        "justification": f"{role} requires {effective_floor}; cheapest eligible candidate uses verified cost/tokens when available",
    }


def activity_inputs(root: Path, tasks_path: Path | None, catalog_lock: dict[str, Any]) -> dict[str, Any]:
    state_path = tasks_path.with_name("state.json") if tasks_path else None
    return {
        "tasks": file_hash(tasks_path) if tasks_path else None,
        "state": file_hash(state_path) if state_path else None,
        "catalog": catalog_lock.get("fingerprint"),
    }


def generic_route(target: str) -> dict[str, Any]:
    policy = routing.load_policy()
    complexity, risk, source, confidence, reasons = routing.infer_classification(target, target, {}, policy["defaults"])
    task = routing.TaskDefinition(
        task_id="T000", title=target, dependencies=(), complexity=complexity, risk=risk,
        domains=("unknown",), capabilities=("coding",), parallelizable=False,
        conflicts=("unknown-boundary",), verification=(), gates=(),
        classification_source=source, classification_confidence=confidence,
        classification_reasons=reasons,
    )
    return routing.route_task(task, policy["defaults"]["executionPolicy"], policy)


def create_proposal(
    root: Path,
    manifest: dict[str, Any],
    workflow: str,
    target: str,
    provider: str | None,
    requested_harness: str | None,
) -> dict[str, Any]:
    harness = select_harness(manifest, requested_harness)
    effective_provider, scope = resolve_provider_scope(manifest, provider)
    lock = catalog.load_catalog(root)
    harness = select_harness(manifest, requested_harness)
    lock = catalog.load_catalog(root)
    errors = catalog.validate_catalog(lock, [harness])
    if errors:
        raise ValueError("; ".join(errors))
    # Project overrides enrich the canonical catalog; routing never contains
    # provider/model-specific policy itself.
    overrides = manifest.get("model_metadata")
    if isinstance(overrides, dict):
        lock = json.loads(json.dumps(lock))
        for harness_entry in lock.get("harnesses", {}).values():
            if isinstance(harness_entry, dict) and isinstance(harness_entry.get("models"), list):
                harness_entry["models"] = catalog.apply_metadata_overrides(harness_entry["models"], overrides)
    tasks_path, task_id, feature = locate_task(root, target)
    if tasks_path and task_id:
        tasks, execution = routing.parse_tasks(tasks_path)
        errors = routing.validate_definitions(tasks, execution, routing.load_policy())
        if errors:
            raise ValueError("routing validation failed: " + "; ".join(errors))
        selected_task = tasks[task_id]
        current: dict[str, Any] = {}
        state_path = tasks_path.with_name("state.json")
        if state_path.is_file():
            state = read_json(state_path, "adjacent feature state")
            state_errors = routing.state_tool.validate_state(state, expected_feature=feature)
            if state_errors:
                raise ValueError("invalid adjacent state: " + "; ".join(state_errors))
            candidate = state.get("tasks", {}).get(task_id)
            if isinstance(candidate, dict):
                current = candidate
        complexity, risk, _reasons = routing.effective_classification(selected_task, current)
        route = routing.route_task(selected_task, execution, routing.load_policy(), complexity=complexity, risk=risk)
        if current.get("classificationConfidence") in {"MEDIUM", "HIGH"} and selected_task.classification_source != "declared":
            route["classification"] = {
                "source": "persisted",
                "confidence": current["classificationConfidence"],
                "reasons": current.get("classificationReasons", []),
            }
        convergence = current.get("convergence") if isinstance(current.get("convergence"), dict) else {}
        closure = convergence.get("developerClosure") if isinstance(convergence, dict) else None
        capsule = {
            "objective": selected_task.title,
            "acceptanceCriteria": list(selected_task.verification),
            "decisions": [],
            "paths": [value.removeprefix("file:") for value in selected_task.conflicts if value.startswith("file:")],
            "dependencies": list(selected_task.dependencies),
            "knownFailures": closure.get("knownFailures", []) if isinstance(closure, dict) else [],
            "gates": route.get("verify", []),
            "developerClosure": closure,
        }
    else:
        route = generic_route(target)
        capsule = {
            "objective": target,
            "acceptanceCriteria": [],
            "decisions": [],
            "paths": [],
            "dependencies": [],
            "knownFailures": [],
            "gates": route.get("verify", []),
            "developerClosure": None,
        }
    if route.get("classification", {}).get("confidence") == "LOW":
        raise ValueError("CLASSIFICATION_REQUIRED: deterministic inference confidence is low; declare task Complexity and Risk")
    # Invalid enabled decision configuration is a proposal error, not a
    # best-effort runtime/audit failure.
    decision_config = DecisionConfig.from_manifest(manifest)
    decision_pre: dict[str, Any] | None = None
    if decision_config.enabled:
        decision_pre = observe_pre(
            decision_config,
            {
                "id": _decision_task_id(task_id, target),
                "feature": feature or "decision-plane",
                "objective": capsule["objective"],
                "requirements": capsule["acceptanceCriteria"],
            },
            route, {**(current if tasks_path else {}), "executionPolicy": execution, "history": (current.get("history", []) if isinstance(current, dict) else [])}, capsule,
            audit=DecisionAudit(root, decision_config.audit_path),
        )
    mapping = load_mapping(root, harness)
    available_ids = {value["id"] for value in catalog_models(lock, harness, scope)}
    configured_orchestrator = manifest.get("orchestrator_model")
    orchestrator_model = configured_orchestrator if configured_orchestrator in available_ids else None
    roles = [
        proposal_role(
            root, lock, mapping, harness, scope,
            role, family, floor, orchestrator_model,
        )
        for role, family, floor in role_contracts(workflow, route)
    ]
    for role in roles:
        if role["role"] == "orchestrator":
            effort = "medium" if route["class"]["risk"] in {"HIGH", "CRITICAL"} else "low"
        elif role["role"] in {"developer", "qa"}:
            effort = "low"
        else:
            effort = "medium"
        role["recommended"]["reasoningEffort"] = effort
        for alternative in role["alternatives"]:
            alternative["reasoningEffort"] = effort
        role["crossHarnessAlternatives"] = []
        if effective_provider == "auto":
            for alternate_harness in manifest.get("harnesses", []):
                if alternate_harness == harness:
                    continue
                try:
                    alternate = proposal_role(
                        root, lock, load_mapping(root, alternate_harness), alternate_harness, "auto",
                        role["role"], role["family"], role["floor"], None,
                    )
                except ValueError:
                    continue
                for candidate in alternate["alternatives"]:
                    if candidate.get("eligible"):
                        role["crossHarnessAlternatives"].append({**candidate, "harness": alternate_harness})
    inputs = activity_inputs(root, tasks_path, lock)
    identity = {
        "schemaVersion": 1,
        "workflow": workflow,
        "target": target,
        "feature": feature,
        "task": task_id,
        "harness": harness,
        "provider": effective_provider,
        "availableHarnesses": list(manifest.get("harnesses", [])),
        "inputs": inputs,
        "roles": [{"role": value["role"], "model": value["recommended"]["model"]} for value in roles],
    }
    proposal_id = canonical_hash(identity)[:20]
    proposal = {
        **identity,
        "kind": "ModelProposal",
        "proposalId": proposal_id,
        "createdAt": now(),
        "classification": route.get("classification"),
        "taskClass": route.get("class"),
        "verification": route.get("verify", []),
        "contextCapsule": capsule,
        "roles": roles,
        "status": "PROPOSED",
    }
    try:
        correlation = decision_pre.get("correlation_id") if isinstance(decision_pre, dict) else None
        if isinstance(correlation, str):
            _remember_decision_correlation(root, proposal, correlation)
    except Exception:
        pass
    safe_write_json(root / PROPOSALS / f"{proposal_id}.json", proposal)
    return proposal


def load_proposal(root: Path, proposal_id: str) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(proposal_id):
        raise ValueError("invalid proposal id")
    proposal = read_json(root / PROPOSALS / f"{proposal_id}.json", "model proposal")
    if proposal.get("kind") != "ModelProposal" or proposal.get("proposalId") != proposal_id:
        raise ValueError("invalid model proposal")
    return proposal


def current_inputs(root: Path, proposal: dict[str, Any]) -> dict[str, Any]:
    feature = proposal.get("feature")
    tasks_path = root / ".specs" / "features" / str(feature) / "tasks.md"
    lock = catalog.load_catalog(root)
    return activity_inputs(root, tasks_path if tasks_path.is_file() else None, lock)


def parse_overrides(raw_values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError("--model must use role=model-id")
        role, model = raw.split("=", 1)
        if role not in ROLE_ORDER or not model.strip():
            raise ValueError(f"invalid model override: {raw}")
        overrides[role] = model.strip()
    return overrides


def bounded_context_capsule(capsule: dict[str, Any], role: str) -> dict[str, Any]:
    """Pass only role-relevant, bounded evidence; canonical artifacts remain references."""
    budget = ROLE_BUDGETS.get(role, ROLE_BUDGETS["mechanical"])
    compact = dict(capsule)
    compact["budget"] = budget
    compact["artifactReferences"] = [".specs/features/<feature>/state.json", "Developer Closure", "GateReceipt"]
    failures = compact.get("knownFailures")
    if isinstance(failures, list):
        compact["knownFailures"] = [compress_tool_output(str(value), limit=600) for value in failures[:3]]
    for key in ("acceptanceCriteria", "decisions", "paths", "dependencies", "gates"):
        value = compact.get(key)
        if isinstance(value, list):
            compact[key] = value[:12]
    return compact


def current_context_capsule(root: Path, plan: dict[str, Any], role: str) -> dict[str, Any]:
    """Rebuild a small, fact-only capsule immediately before a fresh run."""
    tasks_path, task_id, feature = locate_task(root, str(plan["target"]))
    capsule: dict[str, Any] = {
        "objective": plan["target"], "acceptanceCriteria": [], "decisions": [],
        "paths": [], "dependencies": [], "knownFailures": [], "gates": [],
        "developerClosure": None,
    }
    if tasks_path and task_id:
        tasks, execution = routing.parse_tasks(tasks_path)
        task = tasks[task_id]
        state_path = tasks_path.with_name("state.json")
        current: dict[str, Any] = {}
        state: dict[str, Any] = {}
        if state_path.is_file():
            state = read_json(state_path, "adjacent feature state")
            candidate = state.get("tasks", {}).get(task_id)
            if isinstance(candidate, dict):
                current = candidate
        complexity, risk, _ = routing.effective_classification(task, current)
        route = routing.route_task(task, execution, routing.load_policy(), complexity=complexity, risk=risk)
        convergence = current.get("convergence") if isinstance(current.get("convergence"), dict) else {}
        closure = convergence.get("developerClosure") if isinstance(convergence, dict) else None
        capsule.update({
            "objective": task.title,
            "acceptanceCriteria": list(task.verification),
            "paths": [item.removeprefix("file:") for item in task.conflicts if item.startswith("file:")],
            "dependencies": list(task.dependencies), "gates": route.get("verify", []),
            "developerClosure": closure,
            "knownFailures": closure.get("knownFailures", []) if isinstance(closure, dict) else [],
        })
        findings = convergence.get("reviewFindings", []) if isinstance(convergence, dict) else []
        if role == "developer" and isinstance(findings, list):
            capsule["reviewFindings"] = findings[:12]
        handoff = state.get("handoff") if isinstance(state.get("handoff"), dict) else {}
        if handoff:
            capsule["decisions"] = [str(handoff.get("ads", ""))] if handoff.get("ads") else []
    try:
        diff = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--", *capsule["paths"]], cwd=root,
            text=True, capture_output=True, timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        diff = ""
    if diff:
        capsule["partialChanges"] = compress_tool_output(diff, limit=1200)
    return bounded_context_capsule(capsule, role)


def classify_availability_failure(output: str) -> dict[str, str] | None:
    """Normalize known provider failures without retaining their raw output."""
    text = output.lower()
    if any(token in text for token in ("free usage exceeded", "quota exceeded", "usage limit", "insufficient quota")):
        kind = "quota"
    elif any(token in text for token in ("rate limit", "too many requests", "http 429")):
        kind = "rate_limit"
    elif any(token in text for token in ("model unavailable", "model_not_found", "unavailable model")):
        kind = "model_unavailable"
    elif any(token in text for token in ("context window", "context length", "too many tokens")):
        kind = "context_window"
    else:
        return None
    retry = re.search(r"(?:retry(?: after| in)?|wait)\s*(\d+)\s*(seconds?|minutes?|hours?)", text)
    result = {"kind": kind, "scope": "model"}
    if retry:
        result["retryAfterSeconds"] = str(int(retry.group(1)) * {"second": 1, "seconds": 1, "minute": 60, "minutes": 60, "hour": 3600, "hours": 3600}[retry.group(2)])
    return result


def reported_effective_model(output: str) -> str | None:
    """Read an explicit model receipt when a harness emits structured output."""
    for line in reversed(output.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            value = event.get("effectiveModel") or event.get("model")
            if isinstance(value, str) and value:
                return value
    return None


def reduce_context_capsule(capsule: dict[str, Any]) -> dict[str, Any]:
    """Keep the task boundary when a provider rejects the normal context size."""
    compact = dict(capsule)
    for key, limit in (("acceptanceCriteria", 6), ("paths", 6), ("dependencies", 6), ("gates", 6), ("reviewFindings", 6)):
        if isinstance(compact.get(key), list):
            compact[key] = compact[key][:limit]
    compact.pop("partialChanges", None)
    compact.pop("decisions", None)
    compact["contextReduced"] = True
    return compact


def approve_proposal(root: Path, proposal_id: str, override_values: list[str]) -> dict[str, Any]:
    proposal = load_proposal(root, proposal_id)
    if current_inputs(root, proposal) != proposal.get("inputs"):
        raise ValueError("PROPOSAL_STALE: task, state, or catalog changed; generate a new proposal")
    overrides = parse_overrides(override_values)
    plan_roles: list[dict[str, Any]] = []
    for contract in proposal["roles"]:
        role = contract["role"]
        requested = overrides.get(role, contract["recommended"]["model"])
        candidate = next((value for value in contract["alternatives"] if value["model"] == requested), None)
        if candidate is None:
            raise ValueError(f"model {requested!r} was not discovered for {role} and provider {proposal['provider']}")
        if not candidate.get("eligible"):
            raise ValueError(f"model {requested!r} refused for {role}: {candidate.get('disabledReason')}")
        if contract.get("locked") and requested != contract["recommended"]["model"]:
            raise ValueError("orchestrator model is locked for this installation; use init --force --orchestrator-model")
        eligible_fallback_routes = [
            {
                "model": value["model"], "provider": value["provider"],
                "agent": value.get("agent", role), "reasoningEffort": value["reasoningEffort"],
                "modelClass": value["class"], "harness": proposal["harness"],
            }
            for value in contract["alternatives"]
            if value.get("eligible") and value["model"] != requested
        ]
        eligible_fallback_routes.extend(
            {
                "model": value["model"], "provider": value["provider"],
                "agent": value.get("agent", role), "reasoningEffort": value["reasoningEffort"],
                "modelClass": value["class"], "harness": value["harness"],
            }
            for value in contract.get("crossHarnessAlternatives", [])
            if value.get("model") != requested
        )
        plan_roles.append({
            "role": role,
            "agent": candidate.get("agent", role),
            "model": requested,
            "provider": candidate["provider"],
            "reasoningEffort": candidate["reasoningEffort"],
            "modelClass": candidate["class"],
            "harness": proposal["harness"],
            "requiredFloor": contract["floor"],
            "approvedFallbacks": [value["model"] for value in eligible_fallback_routes],
            "fallbackOrder": eligible_fallback_routes,
            "estimate": candidate["estimate"],
            "contextCapsule": bounded_context_capsule(proposal["contextCapsule"], role),
            "routing": contract.get("routing"),
        })
    plan_id = canonical_hash({"proposalId": proposal_id, "roles": plan_roles, "inputs": proposal["inputs"]})[:20]
    plan = {
        "schemaVersion": 1,
        "kind": "DispatchPlan",
        "planId": plan_id,
        "proposalId": proposal_id,
        "approvedAt": now(),
        "workflow": proposal["workflow"],
        "target": proposal["target"],
        "feature": proposal.get("feature"),
        "task": proposal.get("task"),
        "harness": proposal["harness"],
        "availableHarnesses": proposal.get("availableHarnesses", [proposal["harness"]]),
        "provider": proposal["provider"],
        "inputs": proposal["inputs"],
        "roles": plan_roles,
        "overrides": overrides,
        "status": "APPROVED",
        "executionPolicy": {"session": "fresh", "resume": False, "fork": False},
    }
    safe_write_json(root / PLANS / f"{plan_id}.json", plan)
    return plan


def load_plan(root: Path, plan_id: str, *, allow_state_change: bool = False) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(plan_id):
        raise ValueError("invalid plan id")
    plan = read_json(root / PLANS / f"{plan_id}.json", "dispatch plan")
    if plan.get("kind") != "DispatchPlan" or plan.get("planId") != plan_id:
        raise ValueError("invalid dispatch plan")
    current = current_inputs(root, plan)
    expected = plan.get("inputs", {})
    compatible = current == expected or (
        allow_state_change
        and current.get("tasks") == expected.get("tasks")
        and current.get("catalog") == expected.get("catalog")
    )
    if not compatible:
        raise ValueError("PLAN_STALE: task, state, or catalog changed; approve a new proposal")
    return plan


def next_fallback(
    root: Path, plan_id: str, role: str, failed_model: str,
    *, failure: dict[str, str] | None = None,
) -> dict[str, Any]:
    plan = load_plan(root, plan_id, allow_state_change=True)
    contract = next((value for value in plan["roles"] if value["role"] == role), None)
    if contract is None:
        raise ValueError(f"role {role!r} is not approved by plan {plan_id}")
    approved = [contract["model"], *contract.get("approvedFallbacks", [])]
    if failed_model not in approved:
        raise ValueError("MODEL_MISMATCH: failed model was not approved")
    path = root / CIRCUITS / f"{plan_id}.json"
    state = read_json(path, "circuit state") if path.is_file() else {"schemaVersion": 1, "planId": plan_id, "failures": {}}
    failures = state.setdefault("failures", {}).setdefault(role, [])
    failed = next((item for item in failures if item.get("model") == failed_model), None)
    if failed is None:
        failed = {"model": failed_model, "at": now()}
        if failure:
            failed.update({key: value for key, value in failure.items() if key in {"kind", "scope", "retryAfterSeconds"}})
        failures.append(failed)
    failed_models = {item.get("model") for item in failures if isinstance(item, dict)}
    replacement = next((model for model in approved if model not in failed_models), None)
    state["updatedAt"] = now()
    safe_write_json(path, state)
    if replacement is None:
        wait = {
            "schemaVersion": 1, "kind": "CapacityWait", "planId": plan_id,
            "role": role, "failedModels": sorted(str(value) for value in failed_models),
            "retryAfterSeconds": failure.get("retryAfterSeconds") if failure else None,
            "at": now(),
        }
        safe_write_json(root / WAITS / f"{plan_id}-{role}.json", {key: value for key, value in wait.items() if value is not None})
        return {key: value for key, value in wait.items() if value is not None}
    route = next(
        (value for value in contract.get("fallbackOrder", []) if value.get("model") == replacement),
        contract,
    )
    return {
        "schemaVersion": 1,
        "kind": "ApprovedFallback",
        "planId": plan_id,
        "role": role,
        "failedModels": [item["model"] for item in failures],
        "model": replacement,
        "provider": route.get("provider", plan["provider"]),
        "agent": route.get("agent", role),
        "reasoningEffort": route.get("reasoningEffort"),
        "harness": route.get("harness", plan["harness"]),
    }


def execution_command(root: Path, route: dict[str, Any], capsule: dict[str, Any]) -> list[str]:
    """Build only fresh-session commands. Resume and fork never appear here."""
    payload = json.dumps({"dispatch": "fresh", "capsule": capsule}, ensure_ascii=False)
    harness = route["harness"]
    binary = shutil.which(harness if harness != "codex" else "codex")
    if not binary:
        raise ValueError(f"HARNESS_UNAVAILABLE: {harness} executable was not found")
    if harness == "opencode":
        return [binary, "run", "--format", "json", "--agent", route["agent"], "--model", route["model"], payload]
    if harness == "codex":
        return [binary, "exec", "--json", "--model", route["model"], payload]
    if harness == "claude":
        return [binary, "--print", "--output-format", "json", "--agent", route["agent"], "--model", route["model"], payload]
    if harness == "copilot":
        return [binary, "--prompt", payload, "--agent", route["agent"], "--model", route["model"], "--output-format", "json"]
    raise ValueError(f"HARNESS_UNSUPPORTED: {harness}")


def run_dispatch(root: Path, plan_id: str, role: str, *, dry_run: bool = False, timeout: int = 600) -> dict[str, Any]:
    """Run a role in a new CLI process and advance only approved fallbacks."""
    plan = load_plan(root, plan_id, allow_state_change=True)
    contract = next((item for item in plan["roles"] if item["role"] == role), None)
    if contract is None:
        raise ValueError(f"role {role!r} is not approved by plan {plan_id}")
    route = dict(contract)
    attempts: list[dict[str, Any]] = []
    reduce_context = False
    while True:
        capsule = current_context_capsule(root, plan, role)
        if reduce_context:
            capsule = reduce_context_capsule(capsule)
        command = execution_command(root, route, capsule)
        launch = {"harness": route["harness"], "agent": route["agent"], "model": route["model"], "freshSession": True, "command": command[:-1]}
        if dry_run:
            return {"schemaVersion": 1, "kind": "FreshDispatch", "planId": plan_id, "role": role, "capsule": capsule, "launch": launch, "attempts": attempts}
        try:
            completed = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=timeout, check=False)
            output = (completed.stdout + "\n" + completed.stderr).strip()
        except subprocess.TimeoutExpired:
            output = "execution timeout"
            completed = None
        failure = classify_availability_failure(output)
        attempts.append({"model": route["model"], "harness": route["harness"], "result": "availability_failure" if failure else "completed"})
        if failure:
            fallback = next_fallback(root, plan_id, role, route["model"], failure=failure)
            if fallback["kind"] == "ApprovedFallback":
                route = {**contract, **fallback}
                reduce_context = failure["kind"] == "context_window"
                continue
            return {"schemaVersion": 1, "kind": "WaitingForCapacity", "planId": plan_id, "role": role, "wait": fallback, "attempts": attempts}
        if completed is None or completed.returncode:
            return {"schemaVersion": 1, "kind": "DispatchFailure", "planId": plan_id, "role": role, "launch": launch, "attempts": attempts, "result": "FAIL"}
        effective_model = reported_effective_model(output)
        if effective_model and effective_model != route["model"]:
            return {"schemaVersion": 1, "kind": "MODEL_MISMATCH", "planId": plan_id, "role": role, "launch": launch, "attempts": attempts, "requestedModel": route["model"], "effectiveModel": effective_model, "result": "FAIL"}
        receipt = record_receipt(
            root, plan_id, role, "DONE", effective_model or route["model"],
            None, None, None, None, [], effective_harness=route["harness"],
        )
        wait_path = root / WAITS / f"{plan_id}-{role}.json"
        if wait_path.exists():
            wait_path.unlink()
        return {"schemaVersion": 1, "kind": "DispatchCompleted", "planId": plan_id, "role": role, "launch": launch, "attempts": attempts, "effectiveModel": effective_model or route["model"], "receipt": receipt, "result": "DONE"}


def pending_capacity(root: Path, target: str) -> dict[str, Any] | None:
    """Find a recoverable capacity wait for a later `continue` invocation."""
    for path in sorted((root / WAITS).glob("*.json")):
        try:
            wait = read_json(path, "capacity wait")
            plan = load_plan(root, str(wait["planId"]), allow_state_change=True)
        except (KeyError, ValueError):
            continue
        if plan.get("target") == target:
            return wait
    return None


def record_receipt(
    root: Path,
    plan_id: str,
    role: str,
    result: str,
    effective_model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_microunits: int | None,
    cache_tokens: int | None,
    gates: list[str],
    effective_harness: str | None = None,
    manifest: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    plan = load_plan(root, plan_id, allow_state_change=True)
    manifest = manifest if manifest is not None else load_project_manifest(root)
    contract = next((value for value in plan["roles"] if value["role"] == role), None)
    if contract is None:
        raise ValueError(f"role {role!r} is not approved by plan {plan_id}")
    approved_models = [contract["model"], *contract.get("approvedFallbacks", [])]
    if effective_model not in approved_models:
        raise ValueError("MODEL_MISMATCH: effective model was not approved")
    if result not in SAFE_RESULT:
        raise ValueError(f"invalid dispatch result: {result}")
    for name, value in (("input tokens", input_tokens), ("output tokens", output_tokens), ("cache tokens", cache_tokens), ("cost", cost_microunits)):
        if value is not None and (isinstance(value, bool) or value < 0):
            raise ValueError(f"{name} must be a non-negative integer")
    if len(gates) > 20 or any(
        not isinstance(value, str) or not value.strip() or len(value) > 500
        or routing.METRIC_FORBIDDEN.search(value) or routing.state_tool.contains_credential(value)
        for value in gates
    ):
        raise ValueError("gates must be compact fact-only strings without sensitive data")
    actual_class = contract["modelClass"]
    if role == "developer":
        actual_class = next(
            (name for name in CLASS_ORDER if effective_model in routing.mapped_models(plan["harness"], name)),
            catalog.classify_model(effective_model),
        )
    effective_route = next(
        (value for value in contract.get("fallbackOrder", []) if value.get("model") == effective_model),
        contract,
    )
    receipt = {
        "schemaVersion": 1,
        "kind": "DispatchReceipt",
        "planId": plan_id,
        "proposalId": plan["proposalId"],
        "task": plan.get("task") or "T000",
        "feature": plan.get("feature"),
        "role": role,
        "harness": effective_harness or plan["harness"],
        "provider": effective_route["provider"],
        "model": effective_model,
        "modelClass": actual_class,
        "requiredFloor": contract["requiredFloor"],
        "selectionStrategy": (contract.get("routing") or {}).get("selectionStrategy"),
        "requiredCapabilities": (contract.get("routing") or {}).get("requiredCapabilities", []),
        "costTier": next((value.get("costTier") for value in contract.get("fallbackOrder", []) if value.get("model") == effective_model), None),
        "estimatedInputTokens": (contract.get("routing") or {}).get("estimatedInputTokens"),
        "estimatedOutputTokens": (contract.get("routing") or {}).get("estimatedOutputTokens"),
        "estimatedCost": (contract.get("routing") or {}).get("estimatedCost"),
        "actualCost": cost_microunits,
        "escalationCount": 0,
        "escalationReason": None,
        "reasoningEffort": effective_route["reasoningEffort"],
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheTokens": cache_tokens,
        "costMicrounits": cost_microunits,
        "result": result,
        "gates": gates,
        "modelMismatch": effective_model != contract["model"],
        "at": now(),
    }
    compact = {key: value for key, value in receipt.items() if value is not None}
    metric: dict[str, Any] | None = None
    feature = plan.get("feature")
    if role == "developer" and feature and SAFE_ID.fullmatch(str(feature)) and routing.WORK_ITEM_RE.fullmatch(str(receipt["task"])):
        metric = routing.validate_metric_event({
            "task": receipt["task"], "harness": receipt["harness"], "agent": role,
            "model": effective_model, "modelClass": actual_class, "result": result,
            "inputTokens": input_tokens, "outputTokens": output_tokens,
            "costMicrounits": cost_microunits, "at": receipt["at"],
        })
    path = root / RECEIPTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n")
    if metric is not None:
        metric_path = root / ".specs" / "features" / str(feature) / "metrics.jsonl"
        metric_path.parent.mkdir(parents=True, exist_ok=True)
        with metric_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(metric, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        config = DecisionConfig.from_manifest(manifest)
        if config.enabled:
            correlation_id = correlation_id or _find_decision_correlation(root, plan)
            decision_task_id = _decision_task_id(plan.get("task"), str(plan.get("target") or ""))
            observe_post(
                config,
                {"eventualResult": result, "comparison": {}, "usage": {
                    "inputTokens": input_tokens, "outputTokens": output_tokens,
                    "cacheTokens": cache_tokens, "costMicrounits": cost_microunits,
                }, "model": effective_model, "role": role, "gates": gates,
                 "feature": feature or "decision-plane", "task": decision_task_id,
                 "taskId": decision_task_id, "taskContext": contract.get("contextCapsule", {}),
                 "authoritativePreDecision": {"planId": plan_id, "proposalId": plan.get("proposalId"),
                                               "model": contract.get("model"), "provider": contract.get("provider")}},
                root=root, correlation_id=correlation_id,
            )
    except Exception:
        pass
    return compact


def usage_report(root: Path) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = {}
    roles: dict[str, dict[str, int]] = {}
    providers: dict[str, dict[str, int]] = {}
    paths = [root / RECEIPTS]
    feature_root = root / ".specs" / "features"
    if feature_root.is_dir():
        paths.extend(sorted(feature_root.glob("*/metrics.jsonl")))
    seen: set[tuple[Any, ...]] = set()
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (event.get("at"), event.get("task"), event.get("model"), event.get("role") or event.get("agent"), event.get("result"))
            if key in seen:
                continue
            seen.add(key)
            model = str(event.get("model") or "unknown")
            total = totals.setdefault(model, {"runs": 0, "inputTokens": 0, "outputTokens": 0, "cacheTokens": 0, "costMicrounits": 0, "costSamples": 0})
            total["runs"] += 1
            for field in ("inputTokens", "outputTokens", "cacheTokens"):
                if isinstance(event.get(field), int):
                    total[field] += event[field]
            if isinstance(event.get("costMicrounits"), int):
                total["costMicrounits"] += event["costMicrounits"]
                total["costSamples"] += 1
            for group, key_name in ((roles, str(event.get("role") or event.get("agent") or "unknown")), (providers, str(event.get("provider") or "unknown"))):
                grouped = group.setdefault(key_name, {"runs": 0, "inputTokens": 0, "outputTokens": 0, "costMicrounits": 0, "escalations": 0})
                grouped["runs"] += 1
                for field in ("inputTokens", "outputTokens", "costMicrounits"):
                    if isinstance(event.get(field), int):
                        grouped[field] += event[field]
                if isinstance(event.get("escalationCount"), int):
                    grouped["escalations"] += event["escalationCount"]
    return {"schemaVersion": 1, "models": totals, "roles": roles, "providers": providers,
            "costUnknown": any(value["costSamples"] < value["runs"] for value in totals.values())}
