from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


FRAMEWORK = Path(__file__).resolve().parents[1]
CLI = FRAMEWORK / "bin" / "agent-kit"


class AgentKitTest(unittest.TestCase):
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

    def run_cli(self, root: Path, *args: str) -> None:
        subprocess.run([str(CLI), "--root", str(root), *args], check=True, text=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
