#!/usr/bin/env python3
"""Structural framework gate; stdlib only."""
from pathlib import Path
import sys
import math
import re


ROOT = Path(__file__).resolve().parents[1]
IGNORED_POLICY_DIRS = {"__pycache__", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
IGNORED_POLICY_SUFFIXES = {".pyc", ".pyo", ".so", ".dylib", ".dll"}
IGNORED_POLICY_FILES = {".DS_Store"}
REQUIRED = {
    "core": ["principles.md", "orchestration.md", "delegation.md", "handoff.md", "verification.md", "memory.md", "caveman.md", "security.md"],
    "agents": ["orchestrator.md", "explorer.md", "implementer.md", "reviewer.md", "verifier.md"],
    "harness": ["codex.md", "opencode.md", "copilot.md", "claude.md"],
    "profiles": ["generic.md", "flutter.md", "laravel.md", "kotlin-multiplatform.md"],
    "templates": ["agent-framework.toml", "agents-managed-block.md", "ai-memory.toml"],
    "docs": ["model-routing-and-installation.md", "guia-de-uso.md"],
    "state": ["README.md", "schema.json", "state.py", "routing.py", "catalog.py", "activity.py", "environment.py", "validate_state.py", "decision.py", "decision_providers.py", "decision_policy.py", "loop_detector.py", "decision_audit.py", "decision_jev.py", "decision_shadow.py"],
    "workflows": ["manifest.toml", "continue.md", "feature.md", "review.md"],
    "skills/engineering-protocol": ["SKILL.md", "references/routing-policy.json"],
    "tests": [
        "test_agent_kit.py",
        "test_decision_contracts.py",
        "test_decision_providers.py",
        "test_decision_policy.py",
        "test_loop_detector.py",
        "test_decision_audit.py",
        "test_decision_jev.py",
        "test_decision_shadow.py",
        "test_activity_decision_shadow.py",
    ],
    "tests/fixtures/decision": [
        "policy-golden.json",
        "audit-valid.json",
        "audit-invalid.json",
        "contracts-valid.json",
        "contracts-invalid.json",
        "config-valid.toml",
        "config-invalid.toml",
        "shadow-context.json",
        "shadow-config.json",
        "jev-http-request.json",
        "jev-http-response.json",
        "jev-http-invalid.json",
    ],
}


def validate_jev_template(template_text: str) -> list[str]:
    """Return errors for the exact public Jev defaults in the template."""
    expected = {
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
        "timeout": 10.0,
    }
    values: dict[str, object] = {}
    section_seen = False
    current_section = ""
    for line_number, raw_line in enumerate(template_text.splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            if not re.fullmatch(r"\[[A-Za-z0-9_.-]+\]", line):
                return [f"template TOML invalid at line {line_number}"]
            current_section = line[1:-1]
            if current_section == "decision.jev":
                if section_seen:
                    return ["template TOML invalid: duplicate [decision.jev]"]
                section_seen = True
            continue
        if current_section != "decision.jev":
            continue
        assignment = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)", line)
        if not assignment:
            return [f"template TOML invalid at line {line_number}"]
        key, value = assignment.groups()
        if key in values:
            return [f"template TOML invalid: duplicate key {key}"]
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            values[key] = value[1:-1]
        elif key == "timeout":
            try:
                number = float(value)
            except ValueError:
                return [f"template TOML invalid at line {line_number}"]
            if not math.isfinite(number):
                return [f"template TOML invalid at line {line_number}"]
            values[key] = number
        else:
            return [f"template TOML invalid at line {line_number}"]
    jev = values if section_seen else None
    if not isinstance(jev, dict) or set(jev) != set(expected):
        return ["template [decision.jev] must contain exactly endpoint/model/timeout"]
    if jev != expected:
        return ["template [decision.jev] Jev defaults are incorrect"]
    return []


def validate_generic_policy_files() -> list[str]:
    """Check textual generic policy files without touching cache/binary files."""
    errors: list[str] = []
    generic_paths: list[Path] = []
    for scope in (ROOT / "core", ROOT / "skills" / "engineering-protocol", ROOT / "state"):
        if not scope.is_dir():
            continue
        generic_paths.extend(path for path in scope.rglob("*") if path.is_file())
    for path in generic_paths:
        relative_parts = path.relative_to(ROOT).parts
        if any(part in IGNORED_POLICY_DIRS for part in relative_parts) or path.name in IGNORED_POLICY_FILES:
            continue
        if path.suffix.lower() in IGNORED_POLICY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if "/Users/" in text:
            errors.append(f"absolute user path in generic policy: {path.name}")
        if any(token in lowered for token in ("farm management system", "rfid", "weighing")):
            errors.append(f"Farm coupling in generic policy: {path.relative_to(ROOT)}")
    return errors


def main() -> int:
    errors: list[str] = []
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").is_file() else ""
    if not version.startswith("1."):
        errors.append("VERSION must be 1.x")
    for folder, names in REQUIRED.items():
        for name in names:
            if not (ROOT / folder / name).is_file():
                errors.append(f"missing {folder}/{name}")
    template = ROOT / "templates/agents-managed-block.md"
    text = template.read_text(encoding="utf-8") if template.is_file() else ""
    if text.count("<!-- agent-framework:start -->") != 1 or text.count("<!-- agent-framework:end -->") != 1:
        errors.append("managed block markers invalid")
    if "<!-- ai-memory:" in text:
        errors.append("managed block must not contain ai-memory markers")
    workflows = ROOT / "workflows" / "manifest.toml"
    if workflows.is_file():
        workflow_text = workflows.read_text(encoding="utf-8")
        for name in ("continue", "feature", "review"):
            if f'name = "{name}"' not in workflow_text:
                errors.append(f"workflow manifest missing {name}")
    template_text = (ROOT / "templates/agent-framework.toml").read_text(encoding="utf-8") if (ROOT / "templates/agent-framework.toml").is_file() else ""
    for section in ("[decision]", "[decision.policy]", "[decision.context]", "[decision.jev]"):
        if section not in template_text:
            errors.append(f"template missing Decision Plane section {section}")
    errors.extend(validate_jev_template(template_text))
    agent_kit = ROOT / "bin/agent-kit"
    agent_kit_text = agent_kit.read_text(encoding="utf-8") if agent_kit.is_file() else ""
    if '"docs"' not in agent_kit_text or "def copy_assets" not in agent_kit_text:
        errors.append("agent-kit sync missing managed docs capability")
    document_checks = {
        "README.md": (
            "Decision Plane",
            ".specs/features/decision-plane-foundation/design.md",
            "docs/model-routing-and-installation.md",
            "UNSUPPORTED",
        ),
        "docs/model-routing-and-installation.md": (
            "Decision Plane",
            "[decision]",
            "audit",
            "Jev",
        ),
    }
    for filename, references in document_checks.items():
        path = ROOT / filename
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        for reference in references:
            if reference not in text:
                errors.append(f"{filename} missing Decision Plane reference: {reference}")
    jev_source = ROOT / "state/decision_jev.py"
    jev_text = jev_source.read_text(encoding="utf-8") if jev_source.is_file() else ""
    for capability in ("JevDecisionProvider", "TYPESAFE_API_KEY", "jev-latest"):
        if capability not in jev_text:
            errors.append(f"state/decision_jev.py missing Jev capability: {capability}")
    for filename, references in {
        "docs/model-routing-and-installation.md": (
            "api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY", "agent-kit sync",
        ),
    }.items():
        text = (ROOT / filename).read_text(encoding="utf-8") if (ROOT / filename).is_file() else ""
        for reference in references:
            if reference not in text:
                errors.append(f"{filename} missing Jev reference: {reference}")
    agent_kit_tests = ROOT / "tests/test_agent_kit.py"
    agent_kit_test_text = agent_kit_tests.read_text(encoding="utf-8") if agent_kit_tests.is_file() else ""
    for marker in (
        "JevDecisionProvider", "model-routing-and-installation.md", "before_manifest",
        "second", "TYPESAFE_API_KEY", "sitecustomize.py", "network access",
        "PYTHONPATH", "idempotent",
    ):
        if marker not in agent_kit_test_text:
            errors.append(f"tests/test_agent_kit.py missing managed Jev QA marker: {marker}")
    errors.extend(validate_generic_policy_files())
    if errors:
        print("validate_framework: FAIL")
        print("\n".join(errors))
        return 1
    print("validate_framework: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
