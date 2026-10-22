#!/usr/bin/env python3
"""Opt-in native OpenCode adapter smoke test; never sends an AI prompt.

Uses the supplied binary, temporary consumer/config/data directories, read-only
metadata queries, and a private V2 server. Does not install/upgrade OpenCode.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from state.opencode_compat import version_major  # noqa: E402


def run(binary: str, args: list[str], root: Path, env: dict) -> str:
    # V1 can exit before large piped debug output flushes. Regular temporary
    # files also keep private native diagnostics out of the calling terminal.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error:
        result = subprocess.run([binary, *args], cwd=root, env=env, stdout=output,
                                stderr=error, text=True, timeout=30, check=False)
        if result.returncode:
            raise ValueError(f"native command failed: {' '.join(args)} (exit {result.returncode}); inspect the runtime locally")
        output.seek(0)
        return output.read()


def verify_agents(agents: dict, expected: dict, major: int) -> None:
    for name, contract in expected.items():
        agent = agents.get(name)
        if not isinstance(agent, dict) or agent.get("mode") != contract["mode"]:
            raise ValueError(f"agent missing or mode mismatch: {name}")
        model = agent.get("model")
        if isinstance(model, dict):
            model = f"{model.get('providerID')}/{model.get('id')}"
        if model != contract["model"]:
            raise ValueError(f"model mismatch: {name}")
        effort = agent.get("options", {}).get("reasoningEffort") if major == 1 else agent.get("request", {}).get("body", {}).get("reasoningEffort")
        if effort != contract["effort"]:
            raise ValueError(f"reasoning effort mismatch: {name}")
        if major == 1:
            permission = agent.get("permission", {})
            if permission.get("external_directory") != "ask":
                raise ValueError(f"external-directory boundary missing: {name}")
            if name != "orchestrator" and permission.get("task") != "deny":
                raise ValueError(f"child delegation boundary missing: {name}")
            if name.startswith(("reviewer", "qa")) and permission.get("edit") != "deny":
                raise ValueError(f"read-only boundary missing: {name}")
        else:
            rules = agent.get("permissions", [])
            checks = [("external_directory", "ask")]
            if name != "orchestrator":
                checks.append(("subagent", "deny"))
            if name.startswith(("reviewer", "qa")):
                checks.extend((("edit", "deny"), ("*", "deny")))
            for action, effect in checks:
                if {"action": action, "resource": "*", "effect": effect} not in rules:
                    raise ValueError(f"normalized permission missing: {name}/{action}")


def probe(binary: str, temporary: Path) -> dict:
    consumer = temporary / "consumer"
    consumer.mkdir()
    env = dict(os.environ)
    # Do not inherit user-selected server/config overrides into this test.
    for key in list(env):
        if key.startswith("OPENCODE_"):
            del env[key]
    for key, folder in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                        ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        env[key] = str(temporary / folder)
    env["OPENCODE_PASSWORD"] = secrets.token_urlsafe(32)
    major = version_major(run(binary, ["--version"], consumer, env))
    if major not in (1, 2):
        raise ValueError("installed OpenCode major is unknown or unsupported")
    kit = SourceFileLoader("agent_kit_native_probe", str(ROOT / "bin/agent-kit")).load_module()
    templates = kit.harness_templates("opencode", profile="generic")
    expected = {}
    for name, text in templates.items():
        target = consumer / ".opencode" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if name.startswith("agents/"):
            expected[Path(name).stem] = {
                "mode": "primary" if Path(name).stem == "orchestrator" else "subagent",
                "model": re.search(r'^model: "([^"\n]+)"$', text, re.M)[1],
                "effort": re.search(r'^reasoningEffort: (\w+)$', text, re.M)[1],
            }
    for workflow, description in kit.WORKFLOWS.items():
        target = consumer / ".opencode/commands" / f"{workflow}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(kit.managed_command(workflow, description), encoding="utf-8")
    destination = consumer / kit.MANAGED_REL / "skills/engineering-protocol"
    shutil.copytree(ROOT / "skills/engineering-protocol", destination)
    if major == 1:
        config = json.loads(run(binary, ["debug", "config"], consumer, env))
        agents = config.get("agent", {})
        if config.get("default_agent") != "orchestrator":
            raise ValueError("default agent mismatch")
        skills = json.loads(run(binary, ["debug", "skill"], consumer, env))
        commands = config.get("command", {})
    else:
        server = None
        try:
            with (temporary / "server.log").open("w+") as log:
                server = subprocess.Popen([binary, "serve", "--hostname", "127.0.0.1", "--port", "0"],
                                          cwd=consumer, env=env, stdout=log, stderr=log)
                deadline = time.monotonic() + 10
                url = None
                while time.monotonic() < deadline and server.poll() is None:
                    log.seek(0)
                    match = re.search(r"https?://127\.0\.0\.1:\d+", log.read())
                    if match:
                        url = match[0]
                        break
                    time.sleep(.1)
                if not url:
                    raise ValueError("private OpenCode server did not become ready")
                def query(operation):
                    value = json.loads(run(binary, ["api", "--server", url, operation], consumer, env))
                    return value.get("data", []) if isinstance(value, dict) else value
                # File-backed registries initialize asynchronously. Bound readiness
                # polling; never confuse an initial empty list with successful load.
                deadline = time.monotonic() + 10
                while True:
                    skills = query("skill.list")
                    commands = query("command.list")
                    agents = {item["id"]: item for item in query("agent.list")}
                    skill_names = {item.get("id", item.get("name")) for item in skills}
                    command_names = {item.get("name") for item in commands}
                    ready = set(expected) <= set(agents) and "engineering-protocol" in skill_names and set(kit.WORKFLOWS) <= command_names
                    if ready or time.monotonic() >= deadline:
                        break
                    time.sleep(.2)
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    verify_agents(agents, expected, major)
    names = {item.get("id", item.get("name")) for item in skills}
    if "engineering-protocol" not in names:
        raise ValueError("engineering-protocol skill was not discovered")
    command_names = set(commands) if isinstance(commands, dict) else {item.get("name") for item in commands}
    if not set(kit.WORKFLOWS) <= command_names:
        raise ValueError("framework workflow commands were not discovered")
    return {"major": major, "agents": len(expected), "skill": "engineering-protocol",
            "commands": sorted(kit.WORKFLOWS), "normalizedRoleBoundaries": "PASS", "aiCalls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="opencode")
    args = parser.parse_args()
    binary = shutil.which(args.binary)
    if binary is None:
        print("validate_opencode: BLOCKED (binary not found)")
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="aef-opencode-") as raw:
            evidence = probe(binary, Path(raw).resolve())
        print("validate_opencode: PASS " + json.dumps(evidence, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        # Do not print native config/logs or their potentially private contents.
        print(f"validate_opencode: FAIL ({type(error).__name__}: {error})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
