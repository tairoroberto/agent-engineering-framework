#!/usr/bin/env python3
"""Structural framework gate; stdlib only."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "core": ["principles.md", "orchestration.md", "delegation.md", "handoff.md", "verification.md", "memory.md", "caveman.md", "security.md"],
    "agents": ["orchestrator.md", "explorer.md", "implementer.md", "reviewer.md", "verifier.md"],
    "harness": ["codex.md", "opencode.md", "copilot.md", "claude.md"],
    "profiles": ["generic.md", "flutter.md", "laravel.md", "kotlin-multiplatform.md"],
    "templates": ["agent-framework.toml", "agents-managed-block.md", "ai-memory.toml"],
    "docs": ["model-routing-and-installation.md", "guia-de-uso.md"],
    "state": ["README.md", "schema.json", "state.py", "routing.py", "catalog.py", "activity.py", "environment.py", "validate_state.py"],
    "workflows": ["manifest.toml", "continue.md", "feature.md", "review.md"],
    "skills/engineering-protocol": ["SKILL.md", "references/routing-policy.json"],
}


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
    generic_paths = [*(ROOT / "core").glob("*.md"), *(ROOT / "skills" / "engineering-protocol").rglob("*"), *(ROOT / "state").rglob("*")]
    for path in generic_paths:
        if not path.is_file():
            continue
        if "/Users/" in path.read_text(encoding="utf-8"):
            errors.append(f"absolute user path in generic policy: {path.name}")
        if path.suffix in {".md", ".json"} and any(token in path.read_text(encoding="utf-8").lower() for token in ("farm management system", "rfid", "weighing")):
            errors.append(f"Farm coupling in generic policy: {path.relative_to(ROOT)}")
    if errors:
        print("validate_framework: FAIL")
        print("\n".join(errors))
        return 1
    print("validate_framework: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
