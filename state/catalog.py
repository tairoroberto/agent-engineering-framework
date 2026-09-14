#!/usr/bin/env python3
"""Project-local model catalog discovery and locking; Python stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCK_PATH = Path(".agent-managed/model-catalog.lock.json")
HARNESS_ROOTS = {
    "opencode": Path(".opencode"),
    "codex": Path(".codex"),
    "copilot": Path(".github"),
    "claude": Path(".claude"),
}
EXECUTABLES = {"opencode": "opencode", "codex": "codex", "copilot": "copilot", "claude": "claude"}
HARNESS_CAPABILITIES = {
    "opencode": {"modelDiscovery": True, "perInvocationModel": False, "reasoningEffort": True, "effectiveModelReceipt": True},
    "codex": {"modelDiscovery": False, "perInvocationModel": True, "reasoningEffort": True, "effectiveModelReceipt": True},
    "copilot": {"modelDiscovery": False, "perInvocationModel": True, "reasoningEffort": False, "effectiveModelReceipt": True},
    "claude": {"modelDiscovery": False, "perInvocationModel": True, "reasoningEffort": True, "effectiveModelReceipt": True},
}
CLASS_ORDER = (
    "cost-efficient-coding",
    "balanced-coding",
    "strong-coding",
    "strongest-appropriate",
)
MODEL_LINE = re.compile(r"(?<![A-Za-z0-9._/-])([A-Za-z0-9._-]+/[A-Za-z0-9._:@+-]+)(?![A-Za-z0-9._/-])")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(harnesses: dict[str, Any]) -> str:
    canonical = json.dumps({"schemaVersion": 1, "harnesses": harnesses}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def consumer_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".agent-framework.toml").is_file():
            return candidate
    return current


def classify_model(model: str) -> str:
    lowered = model.lower()
    if any(token in lowered for token in ("nano", "mini", "haiku", "flash", "mimo", "luna")):
        return CLASS_ORDER[0]
    if any(token in lowered for token in ("opus", "astra", "ultra", "max")):
        return CLASS_ORDER[3]
    if any(token in lowered for token in ("sol", "pro", "sonnet", "codex", "reason")):
        return CLASS_ORDER[2]
    return CLASS_ORDER[1]


def configured_models(root: Path, harness: str) -> list[dict[str, Any]]:
    path = root / HARNESS_ROOTS[harness] / "routing.json"
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for family in ("modelClasses", "reviewClasses", "qaClasses"):
        entries = mapping.get(family, {}) if isinstance(mapping, dict) else {}
        if not isinstance(entries, dict):
            continue
        for class_name, value in entries.items():
            if not isinstance(value, dict):
                continue
            candidates = value.get("candidates")
            options = candidates if isinstance(candidates, list) else [value]
            for option in options:
                if not isinstance(option, dict) or not isinstance(option.get("model"), str):
                    continue
                model = option["model"]
                provider = str(option.get("provider", harness))
                key = (provider, model)
                entry = found.setdefault(key, {
                    "id": model,
                    "provider": provider,
                    "classes": [],
                    "capabilities": ["coding"],
                    "contextWindow": None,
                    "reasoningEfforts": [],
                    "source": "configured",
                    "available": True,
                    "price": None,
                    "costUnknown": True,
                })
                portable_class = class_name if class_name in CLASS_ORDER else classify_model(model)
                if portable_class not in entry["classes"]:
                    entry["classes"].append(portable_class)
                effort = option.get("reasoningEffort")
                if isinstance(effort, str) and effort not in entry["reasoningEfforts"]:
                    entry["reasoningEfforts"].append(effort)
    return list(found.values())


def discovery_command(harness: str) -> list[str] | None:
    if harness == "opencode":
        return ["opencode", "models"]
    override = os.environ.get(f"AGENT_KIT_{harness.upper()}_MODELS_COMMAND")
    return override.split() if override else None


def discover_models(root: Path, harness: str) -> tuple[list[str], str | None]:
    injected = os.environ.get(f"AGENT_KIT_{harness.upper()}_MODELS")
    if injected is not None:
        return [value.strip() for value in injected.split(",") if value.strip()], "environment"
    command = discovery_command(harness)
    if command is None or shutil.which(EXECUTABLES[harness]) is None:
        return [], None
    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return [], None
    if result.returncode != 0:
        return [], None
    models = list(dict.fromkeys(MODEL_LINE.findall(result.stdout)))
    return models, "harness"


def build_catalog(root: Path, harnesses: list[str], *, discover: bool = True) -> dict[str, Any]:
    catalog_harnesses: dict[str, Any] = {}
    for harness in harnesses:
        configured = configured_models(root, harness)
        by_key = {(entry["provider"], entry["id"]): entry for entry in configured}
        discovered, discovery_source = discover_models(root, harness) if discover else ([], None)
        for model in discovered:
            provider = model.split("/", 1)[0] if "/" in model else harness
            key = (provider, model)
            by_key.setdefault(key, {
                "id": model,
                "provider": provider,
                "classes": [classify_model(model)],
                "capabilities": ["coding"],
                "contextWindow": None,
                "reasoningEfforts": [],
                "source": discovery_source or "harness",
                "available": True,
                "price": None,
                "costUnknown": True,
            })
        models = sorted(by_key.values(), key=lambda item: (item["provider"], item["id"]))
        catalog_harnesses[harness] = {
            "executable": EXECUTABLES[harness],
            "discovery": discovery_source or ("configured" if configured else "unavailable"),
            "capabilities": HARNESS_CAPABILITIES[harness],
            "models": models,
        }
    content = {"schemaVersion": 1, "generatedAt": now(), "harnesses": catalog_harnesses}
    content["fingerprint"] = fingerprint(catalog_harnesses)
    return content


def validate_catalog(value: Any, harnesses: list[str] | None = None) -> list[str]:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        return ["model catalog schemaVersion must be 1"]
    errors: list[str] = []
    catalog_harnesses = value.get("harnesses")
    if not isinstance(catalog_harnesses, dict):
        return ["model catalog harnesses must be object"]
    if value.get("fingerprint") != fingerprint(catalog_harnesses):
        errors.append("model catalog fingerprint mismatch")
    for harness in harnesses or list(catalog_harnesses):
        if harness not in HARNESS_CAPABILITIES:
            errors.append(f"model catalog has unsupported harness {harness}")
            continue
        entry = catalog_harnesses.get(harness)
        if not isinstance(entry, dict):
            errors.append(f"model catalog missing harness {harness}")
            continue
        models = entry.get("models")
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, dict) or not all(isinstance(capabilities.get(key), bool) for key in HARNESS_CAPABILITIES[harness]):
            errors.append(f"model catalog has invalid harness capabilities for {harness}")
        if not isinstance(models, list) or not models:
            errors.append(f"model catalog has no configured models for {harness}")
            continue
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not isinstance(model.get("provider"), str):
                errors.append(f"model catalog has invalid model for {harness}")
                continue
            if not isinstance(model.get("classes"), list) or not isinstance(model.get("capabilities"), list):
                errors.append(f"model catalog lacks capabilities/classes for {harness}:{model.get('id')}")
            if not isinstance(model.get("available"), bool) or not isinstance(model.get("costUnknown"), bool):
                errors.append(f"model catalog lacks availability/cost status for {harness}:{model.get('id')}")
    return errors


def write_catalog(root: Path, value: dict[str, Any]) -> Path:
    path = root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_catalog(root: Path) -> dict[str, Any]:
    path = root / LOCK_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid model catalog lock: {error}") from error
    errors = validate_catalog(value)
    if errors:
        raise ValueError("; ".join(errors))
    return value


def refresh(root: Path, harnesses: list[str], *, discover: bool = True, merge: bool = False) -> dict[str, Any]:
    value = build_catalog(root, harnesses, discover=discover)
    if merge and (root / LOCK_PATH).is_file():
        try:
            current = load_catalog(root)
        except ValueError:
            current = None
        if current is not None:
            combined = dict(current.get("harnesses", {}))
            combined.update(value["harnesses"])
            value["harnesses"] = combined
            value["fingerprint"] = fingerprint(combined)
            value["generatedAt"] = now()
    errors = validate_catalog(value, harnesses)
    if errors:
        raise ValueError("; ".join(errors))
    write_catalog(root, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog.py")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh_parser = sub.add_parser("refresh")
    refresh_parser.add_argument("--harness", action="append", choices=tuple(HARNESS_ROOTS))
    refresh_parser.add_argument("--configured-only", action="store_true")
    show_parser = sub.add_parser("show")
    show_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = consumer_root()
    if args.command == "refresh":
        value = refresh(root, args.harness or list(HARNESS_ROOTS), discover=not args.configured_only, merge=bool(args.harness))
    else:
        value = load_catalog(root)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
