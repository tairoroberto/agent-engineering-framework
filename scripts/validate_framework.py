#!/usr/bin/env python3
"""Structural framework gate; stdlib only."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "core": ["principles.md", "orchestration.md", "delegation.md", "handoff.md", "verification.md", "memory.md", "caverman.md", "security.md"],
    "agents": ["orchestrator.md", "explorer.md", "implementer.md", "reviewer.md", "verifier.md"],
    "harness": ["codex.md", "opencode.md"],
    "profiles": ["generic.md", "flutter.md", "laravel.md"],
    "templates": ["agent-framework.toml", "agents-managed-block.md"],
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
    for path in (ROOT / "core").glob("*.md"):
        if "/Users/" in path.read_text(encoding="utf-8"):
            errors.append(f"absolute user path in core: {path.name}")
    if errors:
        print("validate_framework: FAIL")
        print("\n".join(errors))
        return 1
    print("validate_framework: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
