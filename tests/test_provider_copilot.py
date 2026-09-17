"""OpenCode harness with GitHub Copilot provider (strict, corporate) coverage.

Uses AGENT_KIT_OPENCODE_MODELS injection for deterministic discovery instead
of real Copilot authentication. Authentication itself stays with OpenCode;
no test reads, writes, or asserts on credentials.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


FRAMEWORK = Path(__file__).resolve().parents[1]
CLI = FRAMEWORK / "bin" / "agent-kit"

COPILOT_FIXTURE_MODELS = ",".join((
    "github-copilot/gpt-4o",
    "github-copilot/claude-opus-4.1",
    "github-copilot/claude-sonnet-4.5",
    "github-copilot/gpt-4.1-mini",
    "openai/gpt-6-astra",
    "opencode/big-pickle",
    "opencode/nemotron-3-ultra-free",
))


USER_FIXTURE_MODELS = ",".join((
    "github-copilot/gemini-3.7-flash",
    "github-copilot/gpt-5.3-codex",
    "github-copilot/gpt-5.6-luna",
    "github-copilot/mai-code-1.1-flash",
))


class CopilotProviderTest(unittest.TestCase):
    def run_cli(
        self, root: Path, *args: str, check: bool = True,
        env: dict[str, str] | None = None, models: str | None = COPILOT_FIXTURE_MODELS,
    ) -> subprocess.CompletedProcess[str]:
        merged = {**(env or os.environ)}
        if models is not None:
            merged["AGENT_KIT_OPENCODE_MODELS"] = models
        elif "AGENT_KIT_OPENCODE_MODELS" in merged:
            del merged["AGENT_KIT_OPENCODE_MODELS"]
        return subprocess.run(
            [str(CLI), "--root", str(root), *args], check=check,
            text=True, capture_output=True, env=merged,
        )

    def init_copilot(self, root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            root, "init", "--profile", "flutter",
            "--harness", "opencode", "--provider", "copilot",
            "--memory-workspace", "tests", "--memory-project", root.name,
            *extra,
        )

    def write_task(self, root: Path, task: str = "T33") -> None:
        feature = root / ".specs" / "features" / "checkout"
        feature.mkdir(parents=True, exist_ok=True)
        (feature / "tasks.md").write_text(
            f"### {task}: update checkout copy\n**Complexity**: MEDIUM\n**Risk**: MEDIUM\n",
            encoding="utf-8",
        )

    # CLI

    def test_init_accepts_provider_copilot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.init_copilot(root)
            self.assertIn("PROVIDER: default=copilot", result.stdout)
            manifest = (root / ".agent-framework.toml").read_text(encoding="utf-8")
            self.assertIn('default = "copilot"', manifest)
            self.assertIn('allowed = ["copilot"]', manifest)
            self.assertIn("strict = true", manifest)

    def test_init_force_accepts_provider_copilot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "flutter", "--harness", "opencode",
                         "--memory-workspace", "tests", "--memory-project", root.name)
            result = self.run_cli(
                root, "init", "--force", "--yes", "--harness", "opencode",
                "--provider", "copilot",
            )
            self.assertIn("PROVIDER: default=copilot", result.stdout)
            self.run_cli(root, "doctor")

    def test_init_force_reuses_provider_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            result = self.run_cli(root, "init", "--force", "--yes")
            self.assertIn("PROVIDER: default=copilot", result.stdout)
            manifest = (root / ".agent-framework.toml").read_text(encoding="utf-8")
            self.assertIn('default = "copilot"', manifest)

    def test_init_rejects_invalid_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--profile", "flutter", "--provider", "nope", check=False,
            )
            self.assertNotEqual(0, result.returncode)

    # Manifest

    def test_manifest_persists_default_allowed_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            manifest = (root / ".agent-framework.toml").read_text(encoding="utf-8")
            self.assertIn('default = "copilot"', manifest)
            self.assertIn('allowed = ["copilot"]', manifest)
            self.assertIn("strict = true", manifest)

    # Routing

    def test_opencode_copilot_simulate_returns_executable_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "route", "simulate", "T33", "--workflow", "continue",
                "--harness", "opencode", "--provider", "copilot", "--json",
            ).stdout)
            self.assertEqual("opencode", proposal["harness"])
            self.assertEqual("copilot", proposal["provider"])
            self.assertTrue(proposal["roles"])
            for contract in proposal["roles"]:
                self.assertEqual("copilot", contract["recommended"]["provider"])
                for alternative in contract["alternatives"]:
                    self.assertEqual("copilot", alternative["provider"])

    def test_strict_copilot_rejects_other_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            self.write_task(root)
            refused = self.run_cli(
                root, "route", "simulate", "T33", "--workflow", "continue",
                "--harness", "opencode", "--provider", "openai", "--json", check=False,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("PROVIDER_MISMATCH", refused.stderr)

    def test_omitted_provider_uses_project_default_not_auto(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "continue", "T33", "--harness", "opencode", "--propose", "--json",
            ).stdout)
            self.assertEqual("copilot", proposal["provider"])
            for contract in proposal["roles"]:
                self.assertEqual("copilot", contract["recommended"]["provider"])

    def test_route_explain_shows_only_copilot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            self.write_task(root)
            result = self.run_cli(
                root, "route", "explain", "T33", "--workflow", "continue",
                "--harness", "opencode", "--provider", "copilot",
            )
            self.assertIn("copilot", result.stdout)
            self.assertNotIn("openai", result.stdout)
            self.assertNotIn("openrouter", result.stdout)

    # Orchestrator

    def test_orchestrator_uses_eligible_copilot_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.init_copilot(root)
            self.assertIn("ORCHESTRATOR_MODEL: github-copilot/claude-opus-4.1", result.stdout)

    def test_orchestrator_model_override_validates_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            mismatch = self.run_cli(
                root, "init", "--force", "--yes", "--harness", "opencode",
                "--provider", "copilot", "--orchestrator-model", "openai/gpt-6-astra",
                check=False,
            )
            self.assertNotEqual(0, mismatch.returncode)
            self.assertIn("PROVIDER_MISMATCH", mismatch.stderr)

    def test_orchestrator_unavailable_without_strong_copilot_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            weak = self.run_cli(
                root, "init", "--profile", "flutter", "--harness", "opencode",
                "--provider", "copilot", "--memory-workspace", "tests",
                "--memory-project", root.name,
                models="github-copilot/gpt-4.1-mini", check=False,
            )
            self.assertNotEqual(0, weak.returncode)
            self.assertIn("ORCHESTRATOR_UNAVAILABLE", weak.stderr)

    def test_zero_models_fails_without_silent_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--profile", "flutter", "--harness", "opencode",
                "--provider", "copilot", "--memory-workspace", "tests",
                "--memory-project", root.name, models="", check=False,
            )
            self.assertNotEqual(0, result.returncode)
            combined = result.stdout + result.stderr
            self.assertNotIn("openai/", combined)
            self.assertNotIn("opencode/", combined)

    # Catalog

    def test_catalog_discovers_normalized_copilot_models(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            lock = json.loads(self.run_cli(root, "catalog", "show").stdout)
            copilot = [model for model in lock["harnesses"]["opencode"]["models"]
                       if model["provider"] == "copilot"]
            self.assertEqual(4, len(copilot))
            self.assertTrue(all(model["available"] for model in copilot))
            self.assertTrue(all(model["costUnknown"] for model in copilot))
            refreshed = json.loads(self.run_cli(root, "catalog", "refresh").stdout)
            self.assertIn("fingerprint", refreshed)

    # Doctor

    def test_doctor_passes_for_healthy_opencode_copilot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            result = self.run_cli(root, "doctor")
            self.assertIn("PROVIDER_STATUS copilot: available", result.stdout)
            self.assertIn("DOCTOR: PASS", result.stdout)

    def test_doctor_fails_without_copilot_models(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            result = self.run_cli(root, "doctor", models="", check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("COPILOT_PROVIDER_UNAVAILABLE", result.stdout + result.stderr)

    # Agents

    def test_generated_agents_carry_explicit_provider(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            developer = (root / ".opencode" / "agents" / "developer-copilot.md").read_text(encoding="utf-8")
            self.assertIn("provider=copilot", developer)
            self.assertIn("PROVIDER: copilot", developer)
            orchestrator = (root / ".opencode" / "agents" / "orchestrator.md").read_text(encoding="utf-8")
            self.assertIn("provider=copilot", orchestrator)
            self.assertIn("github-copilot/claude-opus-4.1", orchestrator)
            reviewer = (root / ".opencode" / "agents" / "reviewer-copilot.md").read_text(encoding="utf-8")
            self.assertIn("PROVIDER: copilot", reviewer)

    # Backward compatibility

    def test_legacy_manifest_without_provider_still_resolves_auto(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "opencode",
                         "--memory-workspace", "tests", "--memory-project", root.name)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "continue", "T33", "--harness", "opencode", "--propose", "--json",
            ).stdout)
            self.assertEqual("auto", proposal["provider"])

    def test_opencode_openai_still_routes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "opencode",
                         "--memory-workspace", "tests", "--memory-project", root.name)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "continue", "T33", "--harness", "opencode",
                "--provider", "openai", "--propose", "--json",
            ).stdout)
            self.assertEqual("openai", proposal["provider"])
            developer = next(value for value in proposal["roles"] if value["role"] == "developer")
            self.assertEqual("openai", developer["recommended"]["provider"])

    def test_copilot_harness_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--profile", "generic", "--harness", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
                models=None,
            )
            self.assertIn("ORCHESTRATOR_MODEL: auto", result.stdout)
            self.run_cli(root, "doctor")

    # Provider isolation

    def test_strict_copilot_never_dispatches_other_providers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "continue", "T33", "--harness", "opencode", "--propose", "--json",
            ).stdout)
            forbidden = {"openai", "opencode", "openrouter", "claude", "gemini", "ollama"}
            for contract in proposal["roles"]:
                self.assertNotIn(contract["recommended"]["provider"], forbidden)
                for alternative in contract["alternatives"]:
                    self.assertNotIn(alternative["provider"], forbidden)

    def test_multi_harness_copilot_primary_init_force_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--force", "--yes", "--profile", "flutter",
                "--harness", "copilot", "--harness", "opencode",
                "--provider", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
            )
            self.assertIn("PROVIDER: default=copilot", result.stdout)
            self.assertIn("DOCTOR: PASS", result.stdout)
            self.run_cli(root, "doctor")

    def test_missing_copilot_models_reports_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--force", "--yes", "--profile", "flutter",
                "--harness", "copilot", "--harness", "opencode",
                "--provider", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
                models="", check=False,
            )
            self.assertNotEqual(0, result.returncode)
            combined = result.stdout + result.stderr
            self.assertIn("copilot", combined)
            self.assertIn("probe: no-models", combined)
            self.assertIn("opencode auth login", combined)
            self.assertNotIn("no configured models", combined)

    def test_missing_opencode_binary_reports_install_hint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            env = {**os.environ, "PATH": "/usr/bin:/bin"}
            result = self.run_cli(
                root, "init", "--force", "--yes", "--profile", "flutter",
                "--harness", "opencode",
                "--provider", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
                models=None, env=env, check=False,
            )
            self.assertNotEqual(0, result.returncode)
            combined = result.stdout + result.stderr
            self.assertIn("executable not found in PATH", combined)
            self.assertNotIn("no configured models", combined)

    def test_real_world_entitlement_without_strongest_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--force", "--yes", "--profile", "flutter",
                "--harness", "copilot", "--harness", "opencode",
                "--provider", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
                models=USER_FIXTURE_MODELS,
            )
            self.assertIn("DOCTOR: PASS", result.stdout)
            self.write_task(root)
            proposal = json.loads(self.run_cli(
                root, "route", "simulate", "T33", "--workflow", "continue",
                "--harness", "opencode", "--provider", "copilot", "--json",
                models=USER_FIXTURE_MODELS,
            ).stdout)
            orchestrator = next(value for value in proposal["roles"] if value["role"] == "orchestrator")
            self.assertEqual("github-copilot/gpt-5.3-codex", orchestrator["recommended"]["model"])
            self.assertEqual("copilot", orchestrator["recommended"]["provider"])
            for contract in proposal["roles"]:
                self.assertEqual("copilot", contract["recommended"]["provider"])

    def test_filtered_probe_fallback_when_full_list_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "consumer"
            root.mkdir()
            fake_bin = base / "fakebin"
            fake_bin.mkdir()
            (fake_bin / "opencode").write_text(
                "#!/bin/sh\n"
                'if [ "$1" = "models" ] && [ "$2" = "github-copilot" ]; then\n'
                '  echo "github-copilot/gpt-5.3-codex"\n'
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "opencode").chmod(0o755)
            env = {**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin"}
            result = self.run_cli(
                root, "init", "--force", "--yes", "--profile", "flutter",
                "--harness", "opencode",
                "--provider", "copilot",
                "--memory-workspace", "tests", "--memory-project", root.name,
                models=None, env=env,
            )
            self.assertIn("ORCHESTRATOR_MODEL: github-copilot/gpt-5.3-codex", result.stdout)
            self.assertIn("DOCTOR: PASS", result.stdout)

    def test_env_check_reports_copilot_routes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.init_copilot(root)
            result = self.run_cli(root, "env", "--check", "--json", check=False)
            payload = json.loads(result.stdout)
            self.assertIn("project", payload)
            self.assertTrue(payload["project"]["healthy"])
            self.assertTrue(all(
                item["provider"] == "copilot" and item["state"] == "available"
                for item in payload["project"]["providers"]
            ))
            self.assertTrue(all(payload["project"]["routes"].values()))


if __name__ == "__main__":
    unittest.main()
