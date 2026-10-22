"""Acceptance coverage for portable OpenCode 1/2 adapters and CLI contracts."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from importlib.machinery import SourceFileLoader

from state import activity, catalog, opencode_compat as compat, environment

ROOT = Path(__file__).resolve().parents[1]
kit = SourceFileLoader("agent_kit_compat", str(ROOT / "bin/agent-kit")).load_module()


class OpenCodeCompatibilityTest(unittest.TestCase):
    def test_version_detection_accepts_both_release_formats_and_rejects_noise(self):
        for text, expected in (("1.2.3\n", 1), ("opencode v2.1.2", 2),
                               ("2.0.0-beta.4", 2), ("not installed", None),
                               ("error 2.1.2", None), ("3.0.0", 3)):
            with self.subTest(text=text):
                self.assertEqual(expected, compat.version_major(text))

    def test_v2_model_discovery_uses_only_supported_flags(self):
        calls = []
        def run(command, executable, root, **kwargs):
            calls.append(command)
            self.assertEqual(["opencode", "models", "--standalone"], command)
            return 0, "github-copilot/gpt-5.5\nopencode/big-pickle\nopenrouter/anthropic/claude-sonnet-4.5\n"
        with patch.dict(os.environ, {}, clear=True), patch.object(compat, "installed_major", return_value=2), patch.object(catalog, "run_discovery", side_effect=run), patch.object(catalog.shutil, "which", return_value="/bin/opencode"):
            models, source = catalog.discover_models(ROOT, "opencode", providers_hint=["copilot"])
            self.assertEqual("harness", source)
            self.assertEqual({"copilot", "opencode", "openrouter"}, {m["provider"] for m in models})
            self.assertIn("openrouter/anthropic/claude-sonnet-4.5", {m["id"] for m in models})
            status = catalog.provider_discovery_status(ROOT, "opencode", "copilot")
            self.assertEqual(["github-copilot/gpt-5.5"], status["models"])
            self.assertEqual("available", status["state"])
            filtered = catalog.probe_native_providers(ROOT, "opencode", ["copilot"])
            self.assertEqual(["copilot"], [m["provider"] for m in filtered])
        self.assertEqual(3, len(calls))

    def test_v2_failed_probe_does_not_retry_v1_flags_or_report_unavailable_provider_as_available(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(compat, "installed_major", return_value=2), patch.object(catalog, "run_discovery", return_value=(1, "opencode/failure")) as run, patch.object(catalog.shutil, "which", return_value="/bin/opencode"):
            self.assertEqual(([], None), catalog.discover_models(ROOT, "opencode", providers_hint=["copilot"]))
            self.assertEqual(1, run.call_count)
            status = catalog.provider_discovery_status(ROOT, "opencode", "copilot")
            self.assertEqual("provider-unavailable", status["state"])
            self.assertEqual([], status["models"])

    def test_v1_keeps_rich_discovery_and_provider_filtered_fallback(self):
        def run(command, executable, root, **kwargs):
            if command == ["opencode", "models", "--verbose"]:
                return 0, 'opencode/big-pickle\n{"id":"big-pickle","providerID":"opencode","capabilities":{"reasoning":true}}\n'
            if command == ["opencode", "models", "github-copilot", "--verbose"]:
                return 1, ""
            if command == ["opencode", "models", "github-copilot"]:
                return 0, "github-copilot/gpt-5.5\n"
            self.fail(f"unsupported V1 command {command}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat, "installed_major", return_value=1), patch.object(catalog, "run_discovery", side_effect=run):
            models, _ = catalog.discover_models(ROOT, "opencode")
            self.assertIn("reasoning", models[0]["capabilities"])
            models = catalog.probe_native_providers(ROOT, "opencode", ["copilot"])
            self.assertEqual("copilot", models[0]["provider"])

    def test_fresh_dispatch_uses_isolated_v2_server_and_no_auto_approval(self):
        route = {"harness": "opencode", "agent": "developer", "model": "openai/gpt-5.5"}
        for major in (1, 2):
            with self.subTest(major=major), patch.object(compat, "installed_major", return_value=major), patch.object(activity.shutil, "which", return_value="/bin/opencode"):
                command = activity.execution_command(ROOT, route, {})
                self.assertEqual(major == 2, "--standalone" in command)
                self.assertEqual("openai/gpt-5.5", command[command.index("--model") + 1])
                for flag in ("--continue", "--session", "--fork", "--auto"):
                    self.assertNotIn(flag, command)

    def make_adapters(self, root):
        for name, text in kit.harness_templates("opencode", profile="flutter").items():
            path = root / ".opencode" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        skill = root / kit.MANAGED_REL / "skills/engineering-protocol/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text((ROOT / "skills/engineering-protocol/SKILL.md").read_text())

    def test_shared_adapters_expose_skills_routes_and_role_boundaries(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_adapters(root)
            self.assertEqual([], compat.validate_adapters(root))
            for path in (root / ".opencode/agents").glob("*.md"):
                text = path.read_text()
                self.assertIn("external_directory: ask", text)
                self.assertIn("V2 has no LSP runtime", text)
                if path.stem.startswith(("reviewer", "qa")):
                    self.assertIn("  edit: deny", text)
                    self.assertIn("  task: deny", text)
            reviewer = root / ".opencode/agents/reviewer.md"
            reviewer.unlink()
            self.assertTrue(any("routed agent missing: reviewer" in e for e in compat.validate_adapters(root)))

    def test_validator_rejects_missing_skill_description_and_bad_mode(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.make_adapters(root)
            skill = root / kit.MANAGED_REL / "skills/engineering-protocol/SKILL.md"
            skill.write_text("---\nname: engineering-protocol\n---\nbody\n")
            agent = root / ".opencode/agents/developer.md"
            agent.write_text(agent.read_text().replace("mode: subagent", "mode: primary"))
            errors = compat.validate_adapters(root)
            self.assertTrue(any("description missing" in e for e in errors))
            self.assertIn("OpenCode agent mode invalid: developer", errors)

    def test_jsonc_diagnostics_preserve_strings_and_never_expose_values(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = root / "opencode.jsonc"
            config.write_text('''{ // comment
              "plugin": ["private-plugin"], "server": {"secret": "DO_NOT_PRINT"},
              "url": "https://example.test/a,//b", /* comment */
            }''')
            self.assertEqual("https://example.test/a,//b", compat.read_jsonc(config)["url"])
            warnings = compat.configuration_warnings(root, 2)
            self.assertEqual(2, len(warnings))
            self.assertNotIn("DO_NOT_PRINT", " ".join(warnings))
            self.assertNotIn("private-plugin", " ".join(warnings))
            config.write_text('{"agents": {}}')
            self.assertTrue(compat.configuration_warnings(root, 1))

    def test_v2_mcp_jsonc_is_detected_but_legacy_plugin_never_proves_hooks_ready(self):
        class Runner:
            def run(self, argv, **kwargs):
                if "install-hooks" in argv:
                    raise AssertionError("must not install legacy hooks on V2")
                return environment.CommandResult(tuple(argv), 0, stdout="opencode v2.1.2\n")
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            config = home / ".config/opencode/opencode.jsonc"
            config.parent.mkdir(parents=True)
            config.write_text('{"mcp": {"servers": {"ai-memory": {"type": "local", "command": ["ai-memory"]}}},}')
            plugin = config.parent / "plugins/ai-memory.ts"
            plugin.parent.mkdir()
            plugin.write_text("ai-memory legacy plugin")
            context = environment.EnvironmentContext(home, home, Runner(), "Linux", "arm64", lambda _: "/bin/opencode")
            checks = environment.AiMemoryRequirement(())._harness_checks(context, "opencode")
            self.assertEqual(environment.RequirementStatus.OK, checks[0].status)
            self.assertEqual(environment.RequirementStatus.PARTIAL, checks[1].status)
            config.write_text('{"mcp":{"servers":{"ai-memory":{"disabled":true}}}}')
            self.assertFalse(environment.json_mcp_server_configured(config))
            requirement = environment.AiMemoryRequirement(())
            operation = requirement._configure_integration(context, "ai-memory", "opencode", "hooks")
            self.assertFalse(operation.succeeded)
            preview = requirement._integration_preview(context, "ai-memory", "opencode", "hooks")
            self.assertNotIn("install-hooks", " ".join(preview))


if __name__ == "__main__":
    unittest.main()
