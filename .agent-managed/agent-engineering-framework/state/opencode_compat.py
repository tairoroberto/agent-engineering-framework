"""OpenCode 1/2 capability detection and portable adapter diagnostics.

Keep generated files in supported V1 syntax: V2 normalizes it in memory.
Never convert a consumer's native configuration or load plugin code here.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


def version_major(output: str) -> int | None:
    match = re.fullmatch(r"(?:opencode\s+)?v?(\d+)\.\d+\.\d+(?:[-+][\w.-]+)?", output.strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def installed_major(root: Path) -> int | None:
    binary = shutil.which("opencode")
    if not binary:
        return None
    try:
        result = subprocess.run([binary, "--version"], cwd=root, text=True,
                                capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return version_major(result.stdout) if result.returncode == 0 else None


def read_jsonc(path: Path) -> dict:
    """Read JSONC comments/trailing commas without changing quoted strings."""
    text = path.read_text(encoding="utf-8")
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/')
    text = tokens.sub(lambda m: m[0] if m[0].startswith('"') else " ", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])',
                  lambda m: "" if m[0] == "," else m[0], text)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("configuration must be an object")
    return value


def configuration_warnings(root: Path, major: int | None) -> list[str]:
    """Report migration boundaries, never config contents (may contain secrets)."""
    warnings: list[str] = []
    for path in (root / "opencode.json", root / "opencode.jsonc",
                 root / ".opencode/opencode.json", root / ".opencode/opencode.jsonc"):
        if not path.is_file():
            continue
        label = path.relative_to(root).as_posix()
        try:
            config = read_jsonc(path)
        except (OSError, UnicodeError, ValueError):
            warnings.append(f"OpenCode config unreadable or invalid: {label}")
            continue
        native_v2 = any(key in config for key in ("agents", "permissions", "providers", "commands", "plugins", "snapshots"))
        native_v2 = native_v2 or isinstance(config.get("skills"), list) or (
            isinstance(config.get("mcp"), dict) and "servers" in config["mcp"]
        )
        if major == 1 and native_v2:
            warnings.append(f"OpenCode 1 cannot use native V2 fields in {label}; preserve a V1-compatible configuration")
        if major == 2:
            if config.get("plugin") or config.get("plugins"):
                warnings.append(f"OpenCode 2 plugin API changed: verify plugin V2 support in {label}; V1 plugins do not run in V2")
            ignored = sorted(set(config) & {"logLevel", "server", "subagent_depth"})
            if ignored:
                warnings.append(f"OpenCode 2 ignores legacy fields in {label}: {', '.join(ignored)}")
            if config.get("lsp"):
                warnings.append(f"OpenCode 2 has no LSP runtime in {label}; use project lint/typecheck/compiler gates")
    if major == 2 and any((root / ".opencode" / folder).is_dir() for folder in ("plugin", "plugins")):
        warnings.append("OpenCode 2: verify local plugins implement the V2 API; file discovery alone proves no lifecycle compatibility")
    return warnings


def validate_adapters(root: Path) -> list[str]:
    """Validate cross-file contracts of framework-generated adapters, offline.

    This checks our deliberately constrained frontmatter, not arbitrary YAML
    or OpenCode's complete configuration schema. Native debug commands remain
    the authority for effective layered settings.
    """
    errors: list[str] = []
    directory = root / ".opencode"
    try:
        config = read_jsonc(directory / "opencode.json")
        routes = json.loads((directory / "routing.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return ["OpenCode framework config/routing unreadable or invalid"]
    if not isinstance(routes, dict):
        return ["OpenCode routing must be an object"]
    if config.get("default_agent") != "orchestrator":
        errors.append("OpenCode default_agent must select orchestrator")
    skills = config.get("skills")
    if not isinstance(skills, dict) or not isinstance(skills.get("paths"), list):
        errors.append("OpenCode shared skills must use V1-compatible skills.paths")
    else:
        for value in skills["paths"]:
            if not isinstance(value, str):
                errors.append("OpenCode skill path must be a string")
                continue
            if value.startswith("~"):
                continue  # Optional user skills are diagnosed by agent-kit env.
            source = root / value
            found = list(source.glob("*/SKILL.md")) if source.is_dir() else []
            if not found:
                errors.append(f"OpenCode project skills missing: {value}")
            for path in found:
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    errors.append(f"OpenCode skill unreadable: {path.relative_to(root)}")
                    continue
                front = text.split("---", 2)
                if len(front) != 3 or not front[0] == "" or not re.search(r"^description:\s*\S", front[1], re.M):
                    errors.append(f"OpenCode skill description missing: {path.relative_to(root)}")
                if not re.search(rf"^name:\s*{re.escape(path.parent.name)}\s*$", front[1] if len(front) == 3 else "", re.M):
                    errors.append(f"OpenCode skill name must match directory: {path.relative_to(root)}")
    expected: dict[str, str] = {"orchestrator": "primary", "planner": "subagent"}
    for family in ("modelClasses", "reviewClasses", "qaClasses"):
        entries = routes.get(family)
        if not isinstance(entries, dict):
            errors.append(f"OpenCode routing family missing: {family}")
            continue
        for entry in entries.values():
            candidates = entry.get("candidates") if isinstance(entry, dict) else None
            if not isinstance(candidates, list):
                errors.append(f"OpenCode routing candidates invalid: {family}")
                continue
            for candidate in candidates:
                agent = candidate.get("agent") if isinstance(candidate, dict) else None
                if not isinstance(agent, str) or not re.fullmatch(r"[a-z0-9-]+", agent):
                    errors.append("OpenCode route has invalid agent ID")
                else:
                    expected[agent] = "subagent"
    for agent, mode in expected.items():
        path = directory / "agents" / f"{agent}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"OpenCode routed agent missing: {agent}")
            continue
        parts = text.split("---", 2)
        front = parts[1] if len(parts) == 3 and parts[0] == "" else ""
        if not re.search(rf"^mode: {mode}$", front, re.M):
            errors.append(f"OpenCode agent mode invalid: {agent}")
        if not re.search(r'^model: "[^"\s]+/[^"\s]+"$', front, re.M):
            errors.append(f"OpenCode agent model must be provider-qualified: {agent}")
        if "\npermission:\n" not in front:
            errors.append(f"OpenCode agent requires portable V1 permission mapping: {agent}")
        if "\n  external_directory: ask\n" not in front:
            errors.append(f"OpenCode agent external-directory policy missing: {agent}")
        if agent != "orchestrator" and "\n  task: deny\n" not in front:
            errors.append(f"OpenCode child delegation must be denied: {agent}")
    return errors
