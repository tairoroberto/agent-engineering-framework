from __future__ import annotations

import json
import os
import pty
import subprocess
import tempfile
import unittest
from pathlib import Path


FRAMEWORK = Path(__file__).resolve().parents[1]
CLI = FRAMEWORK / "bin" / "agent-kit"
STATE = FRAMEWORK / "state" / "state.py"
ROUTING = FRAMEWORK / "state" / "routing.py"


class AgentKitTest(unittest.TestCase):
    def test_init_offers_idempotent_shell_path_for_zsh_and_bash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            for shell, profile_name in (("/bin/zsh", ".zshrc"), ("/bin/bash", ".bash_profile")):
                root = base / f"consumer-{Path(shell).name}"
                home = base / f"home-{Path(shell).name}"
                root.mkdir()
                home.mkdir()
                env = {**os.environ, "HOME": str(home), "SHELL": shell}

                result = self.run_cli_tty(
                    root,
                    "init", "--profile", "generic", "--harness", "copilot",
                    "--memory-workspace", "tests", "--memory-project", root.name,
                    response="y\n", env=env,
                )

                profile = home / profile_name
                content = profile.read_text(encoding="utf-8")
                self.assertIn("SHELL_PATH: added", result.stdout)
                self.assertIn(str(FRAMEWORK / "bin"), content)
                self.assertEqual(1, content.count("# >>> agent-kit managed PATH >>>"))

                repeated = self.run_cli(root, "init", "--profile", "generic", env=env)
                self.assertIn("SHELL_PATH: preserved", repeated.stdout)
                self.assertEqual(content, profile.read_text(encoding="utf-8"))

    def test_init_shell_path_defaults_to_no_and_preserves_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "consumer"
            home = base / "home"
            root.mkdir()
            home.mkdir()
            profile = home / ".zshrc"
            profile.write_text("# project-owned shell config\n", encoding="utf-8")
            before = profile.read_bytes()
            env = {**os.environ, "HOME": str(home), "SHELL": "/bin/zsh"}

            result = self.run_cli_tty(
                root,
                "init", "--profile", "generic", "--harness", "copilot",
                "--memory-workspace", "tests", "--memory-project", "consumer",
                response="\n", env=env,
            )

            self.assertIn("SHELL_PATH: declined", result.stdout)
            self.assertEqual(before, profile.read_bytes())

    def test_noninteractive_init_does_not_modify_shell_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "consumer"
            home = base / "home"
            root.mkdir()
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "SHELL": "/bin/zsh"}

            result = self.run_cli(
                root, "init", "--profile", "generic", "--harness", "copilot",
                "--memory-workspace", "tests", "--memory-project", "consumer",
                env=env,
            )

            self.assertIn("SHELL_PATH: skipped (non-interactive init)", result.stdout)
            self.assertFalse((home / ".zshrc").exists())

    def test_four_harness_installation_generates_catalog_and_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            result = self.run_cli(
                root, "init", "--profile", "generic",
                "--harness", "codex", "--harness", "opencode",
                "--harness", "copilot", "--harness", "claude",
            )
            self.assertIn("MODEL_CATALOG: created", result.stdout)
            expected = (
                ".codex/agents/orchestrator.toml",
                ".opencode/agents/orchestrator.md",
                ".github/agents/orchestrator.agent.md",
                ".claude/agents/orchestrator.md",
                ".github/prompts/continue.prompt.md",
                ".claude/commands/continue.md",
            )
            for relative in expected:
                self.assertTrue((root / relative).is_file(), relative)
            orchestrator = (root / ".opencode/agents/orchestrator.md").read_text(encoding="utf-8")
            self.assertNotRegex(orchestrator, r"(?m)^steps:", "orchestrator must not stop a long activity at an adapter step cap")
            lock = json.loads((root / ".agent-managed/model-catalog.lock.json").read_text(encoding="utf-8"))
            self.assertEqual({"codex", "opencode", "copilot", "claude"}, set(lock["harnesses"]))
            ledger = json.loads((root / ".agent-managed/harness-adapters.json").read_text(encoding="utf-8"))
            self.assertIn(".opencode/commands/continue.md", ledger)
            self.run_cli(root, "doctor")

    def test_orchestrator_model_override_updates_manifest_and_primary_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "opencode")

            self.run_cli(
                root, "init", "--force", "--yes", "--harness", "opencode",
                "--orchestrator-model", "openai/gpt-6-astra",
            )

            manifest = (root / ".agent-framework.toml").read_text(encoding="utf-8")
            orchestrator = (root / ".opencode/agents/orchestrator.md").read_text(encoding="utf-8")
            self.assertIn('orchestrator_model = "openai/gpt-6-astra"', manifest)
            self.assertIn('model: "openai/gpt-6-astra"', orchestrator)
            self.assertNotRegex(orchestrator, r"(?m)^steps:")
            self.run_cli(root, "doctor")

    def test_claude_orchestrator_has_no_turn_cap_but_workers_remain_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "claude")

            orchestrator = (root / ".claude/agents/orchestrator.md").read_text(encoding="utf-8")
            developer = (root / ".claude/agents/developer.md").read_text(encoding="utf-8")
            self.assertNotIn("maxTurns:", orchestrator)
            self.assertIn("maxTurns: 8", developer)

    def test_init_creates_project_owned_ai_memory_and_sync_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "sample-project"
            root.mkdir()

            result = self.run_cli(
                root,
                "init",
                "--profile",
                "generic",
                "--memory-workspace",
                "sample-workspace",
                "--memory-project",
                "sample-project",
            )
            memory = root / ".ai-memory.toml"
            created = memory.read_bytes()
            self.assertIn("AI_MEMORY: created", result.stdout)
            self.assertIn('workspace = "sample-workspace"', created.decode())
            self.assertIn('project = "sample-project"', created.decode())
            self.assertIn('drop_subagent_captures = "true"', created.decode())

            memory.write_text(memory.read_text(encoding="utf-8") + "\n# project-owned\n", encoding="utf-8")
            customized = memory.read_bytes()
            sync = self.run_cli(root, "sync")
            self.assertIn("AI_MEMORY: preserved", sync.stdout)
            self.assertEqual(customized, memory.read_bytes())

    def test_sync_respects_disabled_ai_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            memory = root / ".ai-memory.toml"
            memory.unlink()
            manifest = root / ".agent-framework.toml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace("ai_memory = true", "ai_memory = false"),
                encoding="utf-8",
            )

            result = self.run_cli(root, "sync")
            self.assertIn("AI_MEMORY: disabled", result.stdout)
            self.assertFalse(memory.exists())
            doctor = self.run_cli(root, "doctor")
            self.assertIn("AI_MEMORY: disabled", doctor.stdout)

    def test_sync_and_force_create_missing_enabled_ai_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            memory = root / ".ai-memory.toml"
            memory.unlink()
            sync = self.run_cli(root, "sync")
            self.assertIn("AI_MEMORY: created", sync.stdout)
            memory.unlink()
            force = self.run_cli(root, "init", "--force", "--yes")
            self.assertIn("AI_MEMORY: created", force.stdout)
            self.assertTrue(memory.is_file())

    def test_profile_memory_denylist_applies_only_at_creation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "laravel")
            memory = root / ".ai-memory.toml"
            created = memory.read_bytes()
            self.assertIn(b"storage/oauth-private.key", created)

            self.run_cli(root, "init", "--force", "--yes", "--profile", "flutter")

            self.assertEqual(created, memory.read_bytes())
            self.assertNotIn(b"android/key.properties", memory.read_bytes())

    def test_invalid_project_owned_ai_memory_is_reported_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            memory = root / ".ai-memory.toml"
            memory.write_text('workspace = "keep"\nthis is invalid\n', encoding="utf-8")
            before = memory.read_bytes()
            init = self.run_cli(root, "init", "--profile", "generic")
            self.assertIn("AI_MEMORY: invalid", init.stdout)
            self.assertEqual(before, memory.read_bytes())
            doctor = self.run_cli(root, "doctor", check=False)
            self.assertNotEqual(0, doctor.returncode)
            self.assertIn("AI_MEMORY: invalid", doctor.stdout)
            self.assertEqual(before, memory.read_bytes())

    def test_init_force_restores_managed_assets_and_preserves_project_data(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            memory = root / ".ai-memory.toml"
            memory.write_text(memory.read_text(encoding="utf-8") + "\n# keep-memory\n", encoding="utf-8")
            memory_before = memory.read_bytes()
            specs = root / ".specs" / "features" / "sample"
            specs.mkdir(parents=True)
            (specs / "state.json").write_text('{"keep":true}\n', encoding="utf-8")
            custom = root / ".opencode" / "agents" / "project-specialist.md"
            custom.write_text("project-owned\n", encoding="utf-8")
            managed = root / ".opencode" / "agents" / "developer.md"
            managed.write_text("locally broken\n", encoding="utf-8")

            result = self.run_cli(root, "init", "--force", "--yes")

            self.assertIn("REINSTALL_BACKUP:", result.stdout)
            self.assertIn("INIT_FORCE: complete", result.stdout)
            self.assertIn("Shared developer adapter", managed.read_text(encoding="utf-8"))
            self.assertEqual(memory_before, memory.read_bytes())
            self.assertEqual('{"keep":true}\n', (specs / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("project-owned\n", custom.read_text(encoding="utf-8"))

    def test_init_force_prunes_only_obsolete_ledger_assets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "opencode", "--harness", "claude")
            custom = root / ".claude" / "project-extension.md"
            custom.write_text("keep\n", encoding="utf-8")
            managed = root / ".claude" / "agents" / "developer.md"
            self.assertTrue(managed.is_file())

            result = self.run_cli(root, "init", "--force", "--yes", "--harness", "opencode")

            self.assertIn("OBSOLETE_ADAPTERS:", result.stdout)
            self.assertFalse(managed.exists())
            self.assertEqual("keep\n", custom.read_text(encoding="utf-8"))
            self.assertTrue((root / ".claude").is_dir())

    def test_init_force_removes_obsolete_managed_commands_not_harness_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic", "--harness", "opencode", "--harness", "claude")
            custom = root / ".opencode" / "project-owned.md"
            custom.write_text("keep\n", encoding="utf-8")

            self.run_cli(root, "init", "--force", "--yes", "--harness", "claude")

            self.assertFalse((root / ".opencode/commands/continue.md").exists())
            self.assertEqual("keep\n", custom.read_text(encoding="utf-8"))
            self.assertTrue((root / ".opencode").is_dir())

    def test_init_force_rolls_back_every_inventoried_path_on_doctor_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            adapter = root / ".opencode" / "agents" / "developer.md"
            adapter.write_text("locally damaged but recoverable\n", encoding="utf-8")
            adapter_before = adapter.read_bytes()
            memory = root / ".ai-memory.toml"
            memory.write_text("invalid project-owned memory\n", encoding="utf-8")
            memory_before = memory.read_bytes()

            result = self.run_cli(root, "init", "--force", "--yes", check=False)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("INIT_FORCE_ROLLBACK:", result.stderr)
            self.assertEqual(adapter_before, adapter.read_bytes())
            self.assertEqual(memory_before, memory.read_bytes())

    def test_init_force_recovers_partial_managed_tree_and_invalid_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            managed = root / ".agent-managed/agent-engineering-framework"
            (managed / "metadata.toml").unlink()
            (root / ".agent-managed/harness-adapters.json").write_text("not-json\n", encoding="utf-8")

            result = self.run_cli(root, "init", "--force", "--yes")

            self.assertIn("INIT_FORCE: complete", result.stdout)
            self.assertTrue((managed / "metadata.toml").is_file())
            json.loads((root / ".agent-managed/harness-adapters.json").read_text(encoding="utf-8"))
            self.run_cli(root, "doctor")

    def test_two_consecutive_forced_reinstalls_are_content_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            self.run_cli(root, "init", "--force", "--yes")
            paths = (
                root / "AGENTS.md",
                root / ".ai-memory.toml",
                root / ".agent-managed/agent-engineering-framework/metadata.toml",
                root / ".agent-managed/harness-adapters.json",
            )
            before = {path: path.read_bytes() for path in paths}

            self.run_cli(root, "init", "--force", "--yes")

            self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_init_doctor_and_double_sync_preserve_project_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            original = "# Project rules\n\n<!-- ai-memory:start -->\nkeep\n<!-- ai-memory:end -->\n"
            (root / "AGENTS.md").write_text(original, encoding="utf-8")
            (root / ".ai-memory.toml").write_text(
                'workspace = "test"\nproject = "test"\ndrop_subagent_captures = "true"\n',
                encoding="utf-8",
            )
            self.run_cli(root, "init", "--profile", "flutter")
            self.run_cli(root, "doctor")
            self.run_cli(root, "status")
            self.run_cli(root, "diff")
            agents_after_init = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Project rules", agents_after_init)
            self.assertIn("<!-- ai-memory:start -->", agents_after_init)
            self.assertEqual(agents_after_init.count("<!-- agent-framework:start -->"), 1)
            managed = root / ".agent-managed/agent-engineering-framework"
            self.assertTrue((managed / "skills/engineering-protocol/SKILL.md").is_file())
            for workflow in ("continue", "feature", "review"):
                self.assertTrue((managed / "workflows" / f"{workflow}.md").is_file())
                command = root / ".opencode" / "commands" / f"{workflow}.md"
                self.assertIn("agent-framework-command:start", command.read_text(encoding="utf-8"))
            self.assertTrue((root / ".opencode" / "opencode.json").is_file())
            self.assertTrue((root / ".opencode" / "gates.md").is_file())
            opencode_routes = json.loads((root / ".opencode" / "routing.json").read_text(encoding="utf-8"))
            self.assertEqual("developer-low", opencode_routes["modelClasses"]["cost-efficient-coding"]["candidates"][0]["agent"])
            self.assertEqual("reviewer", opencode_routes["reviewClasses"]["independent-reviewer"]["candidates"][0]["agent"])
            opencode_routes = json.loads((root / ".opencode" / "routing.json").read_text(encoding="utf-8"))
            self.assertEqual("developer-low", opencode_routes["modelClasses"]["cost-efficient-coding"]["candidates"][0]["agent"])
            self.assertEqual("reviewer", opencode_routes["reviewClasses"]["independent-reviewer"]["candidates"][0]["agent"])
            self.assertEqual("qa-adversarial-openai", opencode_routes["qaClasses"]["qa-adversarial"]["candidates"][1]["agent"])
            self.assertTrue((root / ".opencode" / "agents" / "orchestrator.md").is_file())
            self.assertTrue((root / ".opencode" / "agents" / "reviewer.md").is_file())
            self.assertTrue((root / ".opencode" / "agents" / "qa-adversarial-openai.md").is_file())
            orchestrator = (root / ".opencode" / "agents" / "orchestrator.md").read_text(encoding="utf-8")
            reviewer = (root / ".opencode" / "agents" / "reviewer.md").read_text(encoding="utf-8")
            qa = (root / ".opencode" / "agents" / "qa.md").read_text(encoding="utf-8")
            self.assertIn("task: allow", orchestrator)
            self.assertIn("task: deny", reviewer)
            self.assertIn('edit:\n    "*": deny\n    ".specs/**": allow', orchestrator)
            self.assertIn("never edit production code", orchestrator)
            planner = (root / ".opencode" / "agents" / "planner.md").read_text(encoding="utf-8")
            self.assertIn('edit:\n    "*": deny\n    ".specs/**": allow', planner)
            self.assertIn('bash:\n    "*": deny', planner)
            developer = (root / ".opencode" / "agents" / "developer.md").read_text(encoding="utf-8")
            self.assertIn('".specs/**": deny', developer)
            self.assertIn('bash:\n    "*": ask', developer)
            self.assertIn("Run discovered development gates", developer)
            self.assertIn('"dart format --output=none --set-exit-if-changed *": allow', qa)
            self.assertIn('"flutter analyze*": allow', qa)
            self.assertIn('"flutter test*": allow', qa)
            self.assertNotIn('"dart format *": allow', qa)
            self.assertIn("validation reports", qa)
            self.assertIn("EXTERNAL_DIRTY_WORKTREE", qa)
            self.assertTrue((root / ".codex" / "config.toml").is_file())
            self.assertTrue((root / ".codex" / "agents" / "orchestrator.toml").is_file())
            codex_routes = json.loads((root / ".codex" / "routing.json").read_text(encoding="utf-8"))
            self.assertEqual("developer-medium", codex_routes["modelClasses"]["balanced-coding"]["agent"])
            codex_routes = json.loads((root / ".codex" / "routing.json").read_text(encoding="utf-8"))
            self.assertEqual("developer-medium", codex_routes["modelClasses"]["balanced-coding"]["agent"])
            metadata = (managed / "metadata.toml").read_bytes()
            self.run_cli(root, "sync")
            self.run_cli(root, "sync")
            self.assertEqual((root / "AGENTS.md").read_text(encoding="utf-8"), agents_after_init)
            self.assertEqual((managed / "metadata.toml").read_bytes(), metadata)

    def test_init_backs_up_existing_opencode_workflow_and_sync_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            (root / ".opencode" / "commands").mkdir(parents=True)
            old = root / ".opencode" / "commands" / "feature.md"
            old.write_text("project-owned old command\n", encoding="utf-8")
            (root / ".ai-memory.toml").write_text('drop_subagent_captures = "true"\n', encoding="utf-8")
            self.run_cli(root, "init", "--profile", "generic")
            backup = root / ".agent-managed" / "backups" / "opencode-feature.md.before-agent-framework"
            self.assertEqual(backup.read_text(encoding="utf-8"), "project-owned old command\n")
            generated = old.read_bytes()
            self.run_cli(root, "sync")
            self.run_cli(root, "sync")
            self.assertEqual(old.read_bytes(), generated)

    def test_portable_state_survives_harness_change_and_rejects_session_data(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            (root / ".agent-framework.toml").write_text('framework_version = "1"\n', encoding="utf-8")
            self.run_state(root, "new", "cross-harness")
            self.run_state(root, "set", "cross-harness", "lastHarness", "opencode")
            self.run_state(root, "mark", "cross-harness", "T001", "in_progress")
            self.run_state(root, "gate", "cross-harness", "test", "PASS", "--command", "flutter test", "--evidence", "12 passed")
            self.run_state(root, "handoff", "cross-harness", '{"status":"partial","next":"continue T001"}')
            self.run_state(root, "set", "cross-harness", "lastHarness", "codex")
            result = self.run_state(root, "get", "cross-harness", "--json")
            self.assertIn('"lastHarness": "codex"', result.stdout)
            state = root / ".specs/features/cross-harness/state.json"
            corrupted = json.loads(state.read_text(encoding="utf-8"))
            corrupted["sessionId"] = "forbidden"
            state.write_text(json.dumps(corrupted), encoding="utf-8")
            result = self.run_state(root, "validate", "cross-harness", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sensitive memory key forbidden", result.stderr)

    def test_router_resolves_portable_class_through_harness_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            (root / ".ai-memory.toml").write_text('drop_subagent_captures = "true"\n', encoding="utf-8")
            self.run_cli(root, "init", "--profile", "generic")
            tasks = root / "tasks.md"
            tasks.write_text(
                "### T001: high-risk change\n"
                "**Complexity**: HIGH\n"
                "**Risk**: HIGH\n"
                "**Capabilities**: coding\n"
                "**Parallelizable**: false\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T001", "opencode"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            route = json.loads(result.stdout)
            self.assertEqual("strong-coding", route["exec"]["modelClass"])
            self.assertEqual("developer-high", route["exec"]["agent"])
            self.assertEqual("opencode/muse-spark-1.3-contributor-free", route["exec"]["model"])
            self.assertEqual("opencode", route["exec"]["provider"])
            fallback = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T001", "opencode", "--exclude-model", "opencode/muse-spark-1.3-contributor-free"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            fallback_route = json.loads(fallback.stdout)
            self.assertEqual("developer-critical", fallback_route["exec"]["agent"])
            self.assertTrue(fallback_route["exec"]["fallback"])
            openai = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T001", "opencode", "--provider", "openai"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            openai_route = json.loads(openai.stdout)
            self.assertEqual("developer-high-openai", openai_route["exec"]["agent"])
            self.assertEqual("openai/gpt-5.6-sol", openai_route["exec"]["model"])
            codex = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T001", "codex", "--provider", "openai"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            self.assertEqual("openai", json.loads(codex.stdout)["exec"]["provider"])

            reviewer = subprocess.run(
                ["python3", str(ROUTING), "resolve-class", "opencode", "reviewClasses", "independent-reviewer", "--provider", "openai"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            self.assertEqual("reviewer-openai", json.loads(reviewer.stdout)["exec"]["agent"])
            qa = subprocess.run(
                ["python3", str(ROUTING), "resolve-class", "opencode", "qaClasses", "qa-adversarial", "--provider", "openai"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            self.assertEqual("qa-adversarial-openai", json.loads(qa.stdout)["exec"]["agent"])

    def test_router_preserves_compact_project_task_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            (root / ".ai-memory.toml").write_text('drop_subagent_captures = "true"\n', encoding="utf-8")
            self.run_cli(root, "init", "--profile", "generic")
            tasks = root / "tasks.md"
            tasks.write_text(
                "### T1: existing compact identifier\n"
                "**Complexity**: LOW\n**Risk**: LOW\n**Parallelizable**: false\n"
                "### T34: dependent task\n"
                "**Depends on**: T1\n**Complexity**: MEDIUM\n**Risk**: LOW\n**Parallelizable**: false\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T34", "opencode"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            self.assertEqual("T34", json.loads(result.stdout)["task"])

    def test_unannotated_task_is_inferred_without_silent_medium_high_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            tasks = root / "tasks.md"
            tasks.write_text("### T33: update documentation copy\n", encoding="utf-8")
            result = subprocess.run(
                ["python3", str(ROUTING), "route", str(tasks), "T33"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            route = json.loads(result.stdout)
            self.assertEqual({"complexity": "LOW", "risk": "LOW"}, route["class"])
            self.assertEqual("cost-efficient-coding", route["exec"]["modelClass"])
            self.assertEqual("inferred", route["classification"]["source"])

    def test_low_confidence_inference_blocks_dispatch_and_persists_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            feature = root / ".specs/features/sample"
            feature.mkdir(parents=True)
            tasks = feature / "tasks.md"
            tasks.write_text("### T33: change behavior\n", encoding="utf-8")
            self.run_state(root, "new", "sample")

            subprocess.run(["python3", str(ROUTING), "sync", "sample"], cwd=root, check=True, text=True, capture_output=True)
            state = json.loads((feature / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("LOW", state["tasks"]["T33"]["classificationConfidence"])
            self.assertEqual("classification", state["tasks"]["T33"]["blockReason"])
            self.assertEqual("blocked", state["tasks"]["T33"]["status"])
            resolved = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T33", "opencode"],
                cwd=root, check=False, text=True, capture_output=True,
            )
            self.assertNotEqual(0, resolved.returncode)
            self.assertIn("CLASSIFICATION_REQUIRED", resolved.stderr)

    def test_verified_token_metrics_change_recommendation_within_floor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            feature = root / ".specs" / "features" / "sample"
            feature.mkdir(parents=True)
            tasks = feature / "tasks.md"
            tasks.write_text("### T33: update documentation copy\n", encoding="utf-8")
            events = []
            for model, tokens in (("opencode/mimo-v2.5-free", 1000), ("opencode/big-pickle", 100)):
                for attempt in range(3):
                    events.append(json.dumps({
                        "task": "T33", "harness": "opencode", "agent": "developer",
                        "model": model, "modelClass": "cost-efficient-coding", "result": "PASS",
                        "inputTokens": tokens, "outputTokens": 0, "at": f"2026-09-10T00:00:0{attempt}+00:00",
                    }))
            (feature / "metrics.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T33", "opencode", "--provider", "opencode"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            resolved = json.loads(result.stdout)["exec"]
            self.assertEqual("opencode/big-pickle", resolved["model"])
            self.assertEqual("verified-metrics", resolved["selectionBasis"])

    def test_dispatch_receipts_feed_role_scoped_model_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            feature = root / ".specs" / "features" / "sample"
            feature.mkdir(parents=True)
            tasks = feature / "tasks.md"
            tasks.write_text("### T33: update documentation copy\n", encoding="utf-8")
            events = []
            for model, tokens in (("opencode/mimo-v2.5-free", 1000), ("opencode/big-pickle", 100)):
                for attempt in range(3):
                    events.append(json.dumps({
                        "kind": "DispatchReceipt", "task": "T33", "harness": "opencode",
                        "role": "developer", "model": model,
                        "modelClass": "cost-efficient-coding", "result": "PASS",
                        "inputTokens": tokens, "outputTokens": 0,
                        "at": f"2026-09-10T00:01:0{attempt}+00:00",
                    }))
            receipts = root / ".agent-managed" / "runtime" / "dispatch-receipts.jsonl"
            receipts.parent.mkdir(parents=True)
            receipts.write_text("\n".join(events) + "\n", encoding="utf-8")

            result = subprocess.run(
                ["python3", str(ROUTING), "resolve", str(tasks), "T33", "opencode", "--provider", "opencode"],
                cwd=root, check=True, text=True, capture_output=True,
            )
            resolved = json.loads(result.stdout)["exec"]
            self.assertEqual("opencode/big-pickle", resolved["model"])
            self.assertEqual("verified-metrics", resolved["selectionBasis"])

    def test_activity_proposal_approval_override_staleness_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            feature = root / ".specs" / "features" / "sample"
            feature.mkdir(parents=True)
            tasks = feature / "tasks.md"
            tasks.write_text("### T33: update documentation copy\n", encoding="utf-8")

            proposed = self.run_cli(
                root, "continue", "T33", "--harness", "opencode",
                "--provider", "openai", "--propose", "--json",
            )
            proposal = json.loads(proposed.stdout)
            self.assertEqual("ModelProposal", proposal["kind"])
            self.assertEqual("LOW", proposal["taskClass"]["risk"])
            self.assertEqual("opencode/nemotron-3-ultra-free", proposal["roles"][0]["recommended"]["model"])
            self.assertEqual("opencode", proposal["roles"][0]["recommended"]["provider"])
            self.assertEqual("orchestrator", proposal["roles"][0]["recommended"]["agent"])
            developer = next(value for value in proposal["roles"] if value["role"] == "developer")
            self.assertEqual("openai/gpt-5.6-luna", developer["recommended"]["model"])
            self.assertIn("contextCapsule", proposal)

            approved = self.run_cli(
                root, "continue", "--approve", proposal["proposalId"],
                "--model", "developer=openai/gpt-5.6-sol", "--json",
            )
            plan = json.loads(approved.stdout)
            selected = next(value for value in plan["roles"] if value["role"] == "developer")
            self.assertEqual("openai/gpt-5.6-sol", selected["model"])
            self.assertEqual("developer-high-openai", selected["agent"])
            self.assertEqual("low", selected["reasoningEffort"])
            fallback = json.loads(self.run_cli(
                root, "dispatch", "next-fallback", "--plan", plan["planId"],
                "--role", "developer", "--failed-model", "openai/gpt-5.6-sol", "--json",
            ).stdout)
            self.assertEqual("ApprovedFallback", fallback["kind"])
            self.assertEqual("openai", fallback["provider"])

            mismatch = self.run_cli(
                root, "dispatch", "record", "--plan", plan["planId"],
                "--role", "developer", "--result", "PASS",
                "--effective-model", "unapproved/model", check=False,
            )
            self.assertNotEqual(0, mismatch.returncode)
            self.assertIn("MODEL_MISMATCH", mismatch.stderr)

            receipt = self.run_cli(
                root, "dispatch", "record", "--plan", plan["planId"],
                "--role", "developer", "--result", "PASS",
                "--effective-model", "openai/gpt-5.6-sol",
                "--input-tokens", "120", "--output-tokens", "30", "--cache-tokens", "90", "--json",
            )
            self.assertEqual("DispatchReceipt", json.loads(receipt.stdout)["kind"])
            usage = json.loads(self.run_cli(root, "usage", "report", "--json").stdout)
            self.assertEqual(1, usage["models"]["openai/gpt-5.6-sol"]["runs"])

            next_proposal = json.loads(self.run_cli(
                root, "continue", "T33", "--harness", "opencode",
                "--provider", "openai", "--propose", "--json",
            ).stdout)
            next_developer = next(value for value in next_proposal["roles"] if value["role"] == "developer")
            self.assertEqual("openai/gpt-5.6-luna", next_developer["recommended"]["model"])

            tasks.write_text(tasks.read_text(encoding="utf-8") + "\n**Risk**: MEDIUM\n", encoding="utf-8")
            stale = self.run_cli(root, "continue", "--approve", proposal["proposalId"], check=False)
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("PROPOSAL_STALE", stale.stderr)

            tasks.write_text(
                "### T34: security authorization change\n**Complexity**: HIGH\n**Risk**: HIGH\n",
                encoding="utf-8",
            )
            high = json.loads(self.run_cli(
                root, "continue", "T34", "--harness", "opencode",
                "--provider", "openai", "--propose", "--json",
            ).stdout)
            refused = self.run_cli(
                root, "continue", "--approve", high["proposalId"],
                "--model", "developer=openai/gpt-5.6-luna", check=False,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("below strong-coding floor", refused.stderr)

    def test_noninteractive_activity_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            result = self.run_cli(root, "feature", "small documentation change", check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("INTERACTION_REQUIRED", result.stderr)

    def test_tasks_list_shows_open_tasks_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            self.run_state(root, "new", "sample")
            feature = root / ".specs" / "features" / "sample"
            (feature / "tasks.md").write_text(
                "### T1: Preparar configuração\n"
                "### T2: Implementar integração\n"
                "### T3: Validar entrega\n",
                encoding="utf-8",
            )
            self.run_state(root, "mark", "sample", "T1", "ready")
            self.run_state(root, "mark", "sample", "T2", "passed")
            self.run_state(root, "mark", "sample", "T3", "blocked")
            self.run_state(root, "set", "sample", "currentTask", "T1")

            opened = self.run_cli(root, "tasks", "list")
            self.assertIn("OPEN_TASKS: 2", opened.stdout)
            self.assertIn("T1*\tready", opened.stdout)
            self.assertIn("T3\tblocked", opened.stdout)
            self.assertNotIn("T2\tpassed", opened.stdout)

            blocked = json.loads(self.run_cli(
                root, "tasks", "list", "--feature", "sample",
                "--status", "blocked", "--json",
            ).stdout)
            self.assertEqual(["T3"], [row["task"] for row in blocked["tasks"]])
            all_tasks = json.loads(self.run_cli(root, "tasks", "list", "--all", "--json").stdout)
            self.assertEqual(["T1", "T2", "T3"], [row["task"] for row in all_tasks["tasks"]])

            custom_root = root / ".project-state"
            custom_root.mkdir()
            feature.rename(custom_root / "sample")
            manifest = root / ".agent-framework.toml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'path = ".specs/features"', 'path = ".project-state"',
                ),
                encoding="utf-8",
            )
            custom = json.loads(self.run_cli(root, "tasks", "list", "--json").stdout)
            self.assertEqual(".project-state", custom["statePath"])
            self.assertEqual(["T1", "T3"], [row["task"] for row in custom["tasks"]])

    def test_developer_closure_deduplicates_gates_and_converges_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            feature = root / ".specs" / "features" / "design-system"
            (root / "lib").mkdir()
            component = root / "lib" / "text_field.dart"
            component.write_text("class TextField {}\n", encoding="utf-8")
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T1: implement design system text field and select\n"
                "**Complexity**: LOW\n"
                "**Risk**: LOW\n"
                "**Where**: `lib/text_field.dart`\n"
                "**Gates**: format, static-analysis, focused-tests\n",
                encoding="utf-8",
            )
            self.run_state(root, "new", "design-system")
            subprocess.run(["python3", str(ROUTING), "sync", "design-system"], cwd=root, check=True, text=True, capture_output=True)

            format_command = "dart format lib/text_field.dart"
            self.assertEqual(
                "RUN",
                json.loads(self.run_state(
                    root, "gate-decision", "design-system", "T1", "format",
                    "--command", format_command, "--scope", "lib/text_field.dart",
                ).stdout)["decision"],
            )
            self.run_state(
                root, "gate", "design-system", "developer-format", "PASS",
                "--task", "T1", "--role", "developer", "--kind", "format",
                "--scope", "lib/text_field.dart", "--command", format_command,
                "--evidence", "formatted without changes",
            )
            self.assertEqual(
                "REUSE_PASS",
                json.loads(self.run_state(
                    root, "gate-decision", "design-system", "T1", "format",
                    "--command", format_command, "--scope", "lib/text_field.dart",
                ).stdout)["decision"],
            )
            for gate_id, kind, command in (
                ("developer-analyze", "static-analysis", "flutter analyze"),
                ("developer-tests", "focused-tests", "flutter test test/text_field_test.dart"),
            ):
                self.run_state(
                    root, "gate", "design-system", gate_id, "PASS",
                    "--task", "T1", "--role", "developer", "--kind", kind,
                    "--scope", "lib/text_field.dart", "--command", command,
                    "--evidence", "pass",
                )
            self.run_state(
                root, "developer-close", "design-system", "T1",
                "--require", "format,static-analysis,focused-tests",
                "--scope", "lib/text_field.dart",
            )

            self.run_state(root, "review-start", "design-system", "T1")
            self.run_state(
                root, "review-result", "design-system", "T1", "CHANGES_REQUESTED",
                "--findings", json.dumps([
                    {"severity": "MAJOR", "file": "lib/text_field.dart:1", "issue": "missing select behavior"},
                    {"severity": "MINOR", "file": "lib/text_field.dart:1", "issue": "copy wording"},
                ]),
            )
            after_first_review = json.loads(self.run_state(root, "get", "design-system", "--json").stdout)
            self.assertEqual("fixing", after_first_review["tasks"]["T1"]["status"])
            self.assertEqual(1, after_first_review["tasks"]["T1"]["reviewIteration"])
            self.assertEqual(2, len(after_first_review["tasks"]["T1"]["convergence"]["reviewFindings"]))

            component.write_text("class TextField { String select() => 'ok'; }\n", encoding="utf-8")
            for gate_id, kind, command in (
                ("developer-format", "format", format_command),
                ("developer-analyze", "static-analysis", "flutter analyze"),
                ("developer-tests", "focused-tests", "flutter test test/text_field_test.dart"),
            ):
                self.run_state(
                    root, "gate", "design-system", gate_id, "PASS",
                    "--task", "T1", "--role", "developer", "--kind", kind,
                    "--scope", "lib/text_field.dart", "--command", command,
                    "--evidence", "pass after major fix",
                )
            self.run_state(
                root, "developer-close", "design-system", "T1",
                "--require", "format,static-analysis,focused-tests",
                "--scope", "lib/text_field.dart",
            )
            self.run_state(root, "review-start", "design-system", "T1")
            self.run_state(root, "review-result", "design-system", "T1", "PASS", "--findings", "[]")
            finished = json.loads(self.run_state(root, "get", "design-system", "--json").stdout)
            self.assertEqual("passed", finished["tasks"]["T1"]["status"])
            self.assertEqual(1, finished["metrics"]["tasks"]["T1"]["deduplicatedGateExecutions"])

    def test_same_failed_gate_blocks_without_charging_external_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            feature = root / ".specs" / "features" / "sample"
            (root / "lib").mkdir()
            (root / "lib" / "field.dart").write_text("class Field {}\n", encoding="utf-8")
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T1: validate field\n**Complexity**: LOW\n**Risk**: LOW\n**Where**: `lib/field.dart`\n",
                encoding="utf-8",
            )
            self.run_state(root, "new", "sample")
            subprocess.run(["python3", str(ROUTING), "sync", "sample"], cwd=root, check=True, text=True, capture_output=True)
            self.run_state(
                root, "gate", "sample", "qa-analyze", "PASS",
                "--task", "T1", "--role", "qa", "--kind", "static-analysis",
                "--scope", "lib/field.dart", "--command", "flutter analyze",
                "--evidence", "QA observed a pass",
            )
            self.assertEqual(
                "RUN",
                json.loads(self.run_state(
                    root, "gate-decision", "sample", "T1", "static-analysis",
                    "--command", "flutter analyze", "--scope", "lib/field.dart",
                ).stdout)["decision"],
            )
            self.run_state(
                root, "gate", "sample", "developer-analyze", "FAIL",
                "--task", "T1", "--role", "developer", "--kind", "static-analysis",
                "--scope", "lib/field.dart", "--command", "flutter analyze",
                "--evidence", "missing required member",
            )
            decision = json.loads(self.run_state(
                root, "gate-decision", "sample", "T1", "static-analysis",
                "--command", "flutter analyze", "--scope", "lib/field.dart",
            ).stdout)
            self.assertEqual("BLOCKED_NO_PROGRESS", decision["decision"])
            self.run_state(
                root, "gate", "sample", "qa-environment", "EXTERNAL",
                "--task", "T1", "--role", "qa", "--kind", "required-tests",
                "--scope", "lib/field.dart", "--command", "flutter test",
                "--evidence", "runner unavailable", "--classification", "TOOL_UNAVAILABLE",
            )
            state = json.loads(self.run_state(root, "get", "sample", "--json").stdout)
            convergence = state["tasks"]["T1"]["convergence"]
            self.assertEqual(1, convergence["noProgressRounds"])
            self.assertEqual("human_escalation", state["phase"])
            self.assertEqual(1, state["metrics"]["tasks"]["T1"]["noProgressStops"])

    def test_low_risk_plan_skips_qa_and_carries_developer_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(root, "init", "--profile", "generic")
            feature = root / ".specs" / "features" / "sample"
            (root / "docs").mkdir()
            (root / "docs" / "copy.md").write_text("before\n", encoding="utf-8")
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T1: update copy\n**Complexity**: LOW\n**Risk**: LOW\n"
                "**Where**: `docs/copy.md`\n**Gates**: focused-tests\n",
                encoding="utf-8",
            )
            self.run_state(root, "new", "sample")
            subprocess.run(["python3", str(ROUTING), "sync", "sample"], cwd=root, check=True, text=True, capture_output=True)
            self.run_state(
                root, "gate", "sample", "developer-tests", "PASS",
                "--task", "T1", "--role", "developer", "--kind", "focused-tests",
                "--scope", "docs/copy.md", "--command", "python3 -m unittest",
                "--evidence", "pass",
            )
            self.run_state(
                root, "developer-close", "sample", "T1", "--require", "focused-tests",
                "--scope", "docs/copy.md",
            )
            proposal = json.loads(self.run_cli(
                root, "continue", "T1", "--harness", "codex", "--propose", "--json",
            ).stdout)
            self.assertEqual(
                ["orchestrator", "developer", "reviewer"],
                [role["role"] for role in proposal["roles"]],
            )
            self.assertEqual(
                "VERIFIED",
                proposal["contextCapsule"]["developerClosure"]["status"],
            )

    def test_final_review_major_finding_escalates_instead_of_looping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            feature = root / ".specs" / "features" / "field"
            source = root / "lib" / "field.dart"
            source.parent.mkdir()
            source.write_text("class Field {}\n", encoding="utf-8")
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T1: implement field selection\n**Complexity**: LOW\n**Risk**: LOW\n"
                "**Where**: `lib/field.dart`\n**Gates**: focused-tests\n",
                encoding="utf-8",
            )
            self.run_state(root, "new", "field")
            subprocess.run(["python3", str(ROUTING), "sync", "field"], cwd=root, check=True, text=True, capture_output=True)

            for round_number in (1, 2):
                self.run_state(
                    root, "gate", "field", f"developer-tests-{round_number}", "PASS",
                    "--task", "T1", "--role", "developer", "--kind", "focused-tests",
                    "--scope", "lib/field.dart", "--command", "flutter test test/field_test.dart",
                    "--evidence", f"pass round {round_number}",
                )
                self.run_state(
                    root, "developer-close", "field", "T1", "--require", "focused-tests",
                    "--scope", "lib/field.dart",
                )
                self.run_state(root, "review-start", "field", "T1")
                self.run_state(
                    root, "review-result", "field", "T1", "CHANGES_REQUESTED",
                    "--findings", json.dumps([
                        {"severity": "MAJOR", "file": "lib/field.dart:1", "issue": "selection is still absent"},
                    ]),
                )
                if round_number == 1:
                    source.write_text("class Field { String select() => 'partial'; }\n", encoding="utf-8")

            state = json.loads(self.run_state(root, "get", "field", "--json").stdout)
            task = state["tasks"]["T1"]
            self.assertEqual("blocked", task["status"])
            self.assertEqual("convergence", task["blockReason"])
            self.assertEqual("human_escalation", state["phase"])
            self.assertEqual(2, task["reviewIteration"])

    def test_generated_adapters_allow_developer_validation_but_keep_review_qa_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            self.run_cli(
                root, "init", "--profile", "flutter", "--harness", "opencode",
                "--harness", "codex", "--harness", "copilot", "--harness", "claude",
            )
            developer = (root / ".opencode" / "agents" / "developer.md").read_text(encoding="utf-8")
            reviewer = (root / ".opencode" / "agents" / "reviewer.md").read_text(encoding="utf-8")
            qa = (root / ".opencode" / "agents" / "qa.md").read_text(encoding="utf-8")
            self.assertIn('"*": ask', developer)
            self.assertIn("Run discovered development gates", developer)
            self.assertIn("edit: deny", reviewer)
            self.assertIn("flutter analyze*", qa)
            self.assertIn("Never format or edit source", qa)
            copilot_qa = (root / ".github" / "agents" / "qa.agent.md").read_text(encoding="utf-8")
            claude_qa = (root / ".claude" / "agents" / "qa.md").read_text(encoding="utf-8")
            self.assertIn("tools: [read, search, execute]", copilot_qa)
            self.assertIn("Read, Grep, Glob, Bash", claude_qa)

    def test_existing_v2_state_migrates_to_convergence_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "consumer"
            root.mkdir()
            feature = root / ".specs" / "features" / "sample"
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T1: update copy\n**Complexity**: LOW\n**Risk**: LOW\n",
                encoding="utf-8",
            )
            self.run_state(root, "new", "sample")
            subprocess.run(["python3", str(ROUTING), "sync", "sample"], cwd=root, check=True, text=True, capture_output=True)
            path = feature / "state.json"
            legacy_v2 = json.loads(path.read_text(encoding="utf-8"))
            legacy_v2["executionPolicy"].pop("maxSameGateFailure")
            legacy_v2["executionPolicy"].pop("maxNoProgressRounds")
            legacy_v2["tasks"]["T1"].pop("convergence")
            path.write_text(json.dumps(legacy_v2), encoding="utf-8")

            self.run_state(root, "migrate", "sample")
            self.run_state(root, "validate", "sample")
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(2, migrated["executionPolicy"]["maxSameGateFailure"])
            self.assertEqual(1, migrated["executionPolicy"]["maxNoProgressRounds"])
            self.assertIsNone(migrated["tasks"]["T1"]["convergence"]["developerClosure"])

    def test_env_check_json_is_read_only_and_reports_a_healthy_setup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "consumer"
            home = base / "home"
            fake_bin = base / "bin"
            root.mkdir()
            home.mkdir()
            fake_bin.mkdir()
            self.prepare_healthy_env(root, home, fake_bin)
            env = {**os.environ, "HOME": str(home), "PATH": f"{fake_bin}:/usr/bin"}
            data_before = (home / "Library" / "Application Support" / "ai-memory" / "config.toml").read_bytes()
            caveman_before = (home / ".agents" / "skills" / "caveman" / "SKILL.md").read_bytes()
            tlc_before = (home / ".agents" / "skills" / "tlc-spec-driven" / ".skill-meta.json").read_bytes()

            first = self.run_cli(root, "env", "--check", "--json", env=env)
            second = self.run_cli(root, "env", "--yes", env=env)

            report = json.loads(first.stdout)
            self.assertTrue(report["healthy"])
            self.assertEqual(["node-tooling", "ai-memory", "caveman", "tlc-spec-driven"], [
                item["id"] for item in report["requirements"]
            ])
            self.assertIn("ENVIRONMENT: READY", second.stdout)
            self.assertFalse((home / "Applications").exists())
            self.assertEqual(data_before, (home / "Library" / "Application Support" / "ai-memory" / "config.toml").read_bytes())
            self.assertEqual(caveman_before, (home / ".agents" / "skills" / "caveman" / "SKILL.md").read_bytes())
            self.assertEqual(tlc_before, (home / ".agents" / "skills" / "tlc-spec-driven" / ".skill-meta.json").read_bytes())

    def test_env_decline_and_json_yes_conflict_do_not_change_the_machine(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "consumer"
            home = base / "home"
            fake_bin = base / "bin"
            root.mkdir()
            home.mkdir()
            fake_bin.mkdir()
            for name, body in {
                "node": "echo v22.0.0\n",
                "npm": "echo 10.0.0\n",
                "npx": "if [ \"$1\" = \"--version\" ]; then echo 11.0.0; else exit 0; fi\n",
            }.items():
                self.write_fake_executable(fake_bin, name, body)
            env = {**os.environ, "HOME": str(home), "PATH": f"{fake_bin}:/usr/bin"}

            checked = self.run_cli(root, "env", "--check", env=env, check=False)
            declined = self.run_cli_tty(root, "env", response="\n", env=env, check=False)
            conflict = self.run_cli(root, "env", "--yes", "--json", env=env, check=False)

            self.assertEqual(1, checked.returncode)
            self.assertNotIn("PLANNED CHANGES:", checked.stdout)
            self.assertEqual(1, declined.returncode)
            self.assertIn("PLANNED CHANGES:", declined.stdout)
            self.assertIn("NO CHANGES MADE.", declined.stdout)
            self.assertEqual(2, conflict.returncode)
            self.assertIn("cannot be combined", conflict.stderr)
            self.assertFalse((home / "Applications").exists())

    def prepare_healthy_env(self, root: Path, home: Path, fake_bin: Path) -> None:
        for name, body in {
            "node": "echo v22.0.0\n",
            "npm": "echo 10.0.0\n",
            "npx": (
                "if [ \"$1\" = \"--version\" ]; then echo 11.0.0; "
                "elif [ \"$1\" = \"--no-install\" ]; then echo caveman; fi\n"
            ),
            "ai-memory": "if [ \"$1\" = \"--version\" ]; then echo 'ai-memory 2.1.0'; fi\n",
            "launchctl": "echo 'state = running'\n",
            "curl": "printf 405\n",
            "codex": "exit 0\n",
            "opencode": "exit 0\n",
            "copilot": "exit 0\n",
            "claude": "exit 0\n",
        }.items():
            self.write_fake_executable(fake_bin, name, body)
        data = home / "Library" / "Application Support" / "ai-memory"
        data.mkdir(parents=True)
        (data / "config.toml").write_text("ready = true\n", encoding="utf-8")
        codex = home / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text(
            "[mcp_servers.ai-memory]\ncommand = 'ai-memory'\nhook = 'ai-memory'\n",
            encoding="utf-8",
        )
        opencode = home / ".config" / "opencode"
        (opencode / "plugins").mkdir(parents=True)
        (opencode / "opencode.json").write_text('{"ai-memory": {}}\n', encoding="utf-8")
        (opencode / "plugins" / "ai-memory.ts").write_text("ai-memory\n", encoding="utf-8")
        mcp = root / ".vscode"
        mcp.mkdir()
        (mcp / "mcp.json").write_text('{"ai-memory": {}}\n', encoding="utf-8")
        for skill_name, metadata in (
            ("caveman", None),
            ("tlc-spec-driven", '{"source": "tech-leads-club/agent-skills"}\n'),
        ):
            skill = home / ".agents" / "skills" / skill_name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"---\nname: {skill_name}\n---\n", encoding="utf-8")
            if metadata:
                (skill / ".skill-meta.json").write_text(metadata, encoding="utf-8")

    def write_fake_executable(self, directory: Path, name: str, body: str) -> None:
        path = directory / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_cli(
        self, root: Path, *args: str, check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), "--root", str(root), *args], check=check,
            text=True, capture_output=True, env=env,
        )

    def run_cli_tty(
        self, root: Path, *args: str, response: str,
        env: dict[str, str], check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        master, slave = pty.openpty()
        command = [str(CLI), "--root", str(root), *args]
        process = subprocess.Popen(
            command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        os.close(slave)
        try:
            os.write(master, response.encode())
            stdout, stderr = process.communicate(timeout=20)
        finally:
            os.close(master)
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, command, stdout, stderr)
        return result

    def run_state(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", str(STATE), *args], cwd=root, check=check, text=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
