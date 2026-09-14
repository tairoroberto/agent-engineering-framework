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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import catalog
import routing


RUNTIME = Path(".agent-managed/runtime")
PROPOSALS = RUNTIME / "proposals"
PLANS = RUNTIME / "plans"
RECEIPTS = RUNTIME / "dispatch-receipts.jsonl"
CIRCUITS = RUNTIME / "circuits"
ROLE_ORDER = ("orchestrator", "developer", "reviewer", "qa")
CLASS_ORDER = tuple(routing.MODEL_CLASS_ORDER)
TASK_HEADER_TEMPLATE = r"^###\s+{task}:"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
SAFE_RESULT = {"PASS", "FAIL", "DONE", "BLOCKED", "ESCALATED", "CANCELLED"}


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


def mapping_options(mapping: dict[str, Any], family: str, class_name: str, provider: str) -> list[dict[str, Any]]:
    entry = mapping.get(family, {}).get(class_name)
    if not isinstance(entry, dict):
        return []
    candidates = entry.get("candidates")
    values = candidates if isinstance(candidates, list) else [entry]
    return [
        dict(value) for value in values
        if isinstance(value, dict)
        and isinstance(value.get("model"), str)
        and (provider == "auto" or value.get("provider") == provider)
    ]


def family_model_routes(mapping: dict[str, Any], family: str, provider: str) -> dict[str, dict[str, Any]]:
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


def catalog_models(lock: dict[str, Any], harness: str, provider: str) -> list[dict[str, Any]]:
    entry = lock.get("harnesses", {}).get(harness, {})
    values = entry.get("models", []) if isinstance(entry, dict) else []
    return [
        value for value in values
        if isinstance(value, dict)
        and value.get("available", True)
        and (provider == "auto" or value.get("provider") == provider)
    ]


def role_contracts(workflow: str, route: dict[str, Any]) -> list[tuple[str, str, str]]:
    risk = route["class"]["risk"]
    qa_class = {"LOW": "qa-basic", "MEDIUM": "qa-targeted", "HIGH": "qa-adversarial", "CRITICAL": "qa-adversarial"}[risk]
    contracts: list[tuple[str, str, str]] = [("orchestrator", "modelClasses", "strongest-appropriate")]
    if workflow != "review":
        contracts.append(("developer", "modelClasses", route["exec"]["modelClass"]))
    contracts.append(("reviewer", "reviewClasses", "independent-reviewer"))
    if any(value.startswith("qa-") for value in route.get("verify", [])):
        contracts.append(("qa", "qaClasses", qa_class))
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
    provider: str,
    role: str,
    family: str,
    floor: str,
    orchestrator_model: str | None,
) -> dict[str, Any]:
    floor_rank = class_rank(floor) if family == "modelClasses" else {
        "independent-reviewer": 1,
        "specialist-review": 2,
        "qa-basic": 0,
        "qa-targeted": 1,
        "qa-adversarial": 2,
    }.get(floor, 1)
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
            reason = f"below {floor} floor"
        elif not dispatchable:
            reason = "no generated adapter or per-invocation route"
        estimate = estimate_for(
            root, harness, identifier,
            floor if family == "modelClasses" else candidate_class,
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
            "reasoningEffort": route_entry.get("reasoningEffort") or routing.default_reasoning_effort(family, floor),
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
            raise ValueError(f"{prefix}no eligible {provider} model for {role} at {floor}")
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
        "floor": floor,
        "locked": role == "orchestrator",
        "recommended": chosen,
        "alternatives": alternatives,
        "justification": f"{role} requires {floor}; cheapest eligible candidate uses verified cost/tokens when available",
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
    provider: str,
    requested_harness: str | None,
) -> dict[str, Any]:
    harness = select_harness(manifest, requested_harness)
    lock = catalog.load_catalog(root)
    errors = catalog.validate_catalog(lock, [harness])
    if errors:
        raise ValueError("; ".join(errors))
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
    mapping = load_mapping(root, harness)
    available_ids = {value["id"] for value in catalog_models(lock, harness, "auto")}
    configured_orchestrator = manifest.get("orchestrator_model")
    orchestrator_model = configured_orchestrator if configured_orchestrator in available_ids else None
    roles = [
        proposal_role(
            root, lock, mapping, harness, "auto" if role == "orchestrator" else provider,
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
    inputs = activity_inputs(root, tasks_path, lock)
    identity = {
        "schemaVersion": 1,
        "workflow": workflow,
        "target": target,
        "feature": feature,
        "task": task_id,
        "harness": harness,
        "provider": provider,
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
        eligible_fallback_routes = [] if contract.get("locked") else [
            {
                "model": value["model"], "provider": value["provider"],
                "agent": value.get("agent", role), "reasoningEffort": value["reasoningEffort"],
                "modelClass": value["class"],
            }
            for value in contract["alternatives"]
            if value.get("eligible") and value["model"] != requested
        ]
        plan_roles.append({
            "role": role,
            "agent": candidate.get("agent", role),
            "model": requested,
            "provider": candidate["provider"],
            "reasoningEffort": candidate["reasoningEffort"],
            "modelClass": candidate["class"],
            "requiredFloor": contract["floor"],
            "approvedFallbacks": [value["model"] for value in eligible_fallback_routes],
            "fallbackOrder": eligible_fallback_routes,
            "estimate": candidate["estimate"],
            "contextCapsule": proposal["contextCapsule"],
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
        "provider": proposal["provider"],
        "inputs": proposal["inputs"],
        "roles": plan_roles,
        "overrides": overrides,
        "status": "APPROVED",
    }
    safe_write_json(root / PLANS / f"{plan_id}.json", plan)
    return plan


def load_plan(root: Path, plan_id: str) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(plan_id):
        raise ValueError("invalid plan id")
    plan = read_json(root / PLANS / f"{plan_id}.json", "dispatch plan")
    if plan.get("kind") != "DispatchPlan" or plan.get("planId") != plan_id:
        raise ValueError("invalid dispatch plan")
    if current_inputs(root, plan) != plan.get("inputs"):
        raise ValueError("PLAN_STALE: task, state, or catalog changed; approve a new proposal")
    return plan


def next_fallback(root: Path, plan_id: str, role: str, failed_model: str) -> dict[str, Any]:
    plan = load_plan(root, plan_id)
    contract = next((value for value in plan["roles"] if value["role"] == role), None)
    if contract is None:
        raise ValueError(f"role {role!r} is not approved by plan {plan_id}")
    approved = [contract["model"], *contract.get("approvedFallbacks", [])]
    if failed_model not in approved:
        raise ValueError("MODEL_MISMATCH: failed model was not approved")
    path = root / CIRCUITS / f"{plan_id}.json"
    state = read_json(path, "circuit state") if path.is_file() else {"schemaVersion": 1, "planId": plan_id, "failures": {}}
    failures = state.setdefault("failures", {}).setdefault(role, [])
    if failed_model not in failures:
        failures.append(failed_model)
    replacement = next((model for model in approved if model not in failures), None)
    state["updatedAt"] = now()
    safe_write_json(path, state)
    if replacement is None:
        raise ValueError(f"CIRCUIT_OPEN: no approved fallback remains for {role}; create a new proposal")
    route = next(
        (value for value in contract.get("fallbackOrder", []) if value.get("model") == replacement),
        contract,
    )
    return {
        "schemaVersion": 1,
        "kind": "ApprovedFallback",
        "planId": plan_id,
        "role": role,
        "failedModels": failures,
        "model": replacement,
        "provider": route.get("provider", plan["provider"]),
        "agent": route.get("agent", role),
        "reasoningEffort": route.get("reasoningEffort"),
    }


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
) -> dict[str, Any]:
    plan = load_plan(root, plan_id)
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
        "harness": plan["harness"],
        "provider": effective_route["provider"],
        "model": effective_model,
        "modelClass": actual_class,
        "requiredFloor": contract["requiredFloor"],
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
    return compact


def usage_report(root: Path) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = {}
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
    return {"schemaVersion": 1, "models": totals, "costUnknown": any(value["costSamples"] < value["runs"] for value in totals.values())}
