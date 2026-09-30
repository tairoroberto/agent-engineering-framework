import tempfile
import unittest
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from state import activity
from state.decision_audit import DecisionAudit


PLAN = {
    "proposalId": "proposal",
    "harness": "opencode",
    "provider": "openai",
    "task": "T008",
    "feature": None,
    "roles": [{
        "role": "developer", "model": "model", "modelClass": "standard",
        "requiredFloor": "standard", "provider": "openai",
        "reasoningEffort": "low", "fallbackOrder": [], "routing": {},
    }],
}


class ActivityDecisionShadowTests(unittest.TestCase):
    def test_generic_audit_task_id_is_stable_and_opaque(self):
        target = "Investigate customer alice@example.com"
        task_id = activity._decision_task_id(None, target)
        self.assertRegex(task_id, r"^intent-[0-9a-f]{12}$")
        self.assertEqual(task_id, activity._decision_task_id(None, target))
        self.assertNotIn("alice", task_id)

    def test_generic_pre_and_post_share_opaque_task_id(self):
        target = "Investigate customer alice@example.com"
        task_id = activity._decision_task_id(None, target)
        manifest = {"decision": {"enabled": True}}
        plan = copy.deepcopy(PLAN)
        plan.update({"task": None, "target": target, "feature": None})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = DecisionAudit(root)
            correlation = activity.observe_pre(
                activity.DecisionConfig.from_manifest(manifest),
                {"id": task_id, "feature": "decision-plane", "objective": "safe"},
                audit=audit,
            )["correlation_id"]
            with patch.object(activity, "load_plan", return_value=plan):
                activity.record_receipt(
                    root, "plan", "developer", "DONE", "model", None, None,
                    None, None, [], manifest=manifest, correlation_id=correlation,
                )
            records = [json.loads(line) for line in (root / ".agent-managed/runtime/decision-audit.jsonl").read_text().splitlines()]
            self.assertEqual([task_id, task_id], [record["task"] for record in records])
            self.assertNotIn("alice", json.dumps(records))

    def test_activity_imports_in_package_mode(self):
        completed = subprocess.run(
            [sys.executable, "-c", "from state import activity; assert activity.__name__ == 'state.activity'"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_activity_imports_in_agent_kit_top_level_style(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import runpy; runpy.run_path('bin/agent-kit', run_name='agent_kit_bootstrap'); import activity; from state import decision_shadow, decision_audit, decision_providers; assert decision_shadow.__name__ == 'state.decision_shadow'"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_agent_kit_bootstrap_preserves_package_imports_after_activity(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import runpy; runpy.run_path('bin/agent-kit', run_name='agent_kit_bootstrap'); import activity; import state.decision_shadow, state.decision_audit, state.decision_providers"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def receipt(self, root, manifest=None):
        with patch.object(activity, "load_plan", return_value=PLAN):
            return activity.record_receipt(
                root, "plan", "developer", "DONE", "model", None, None,
                None, None, [], manifest=manifest,
            )

    def test_disabled_is_byte_equivalent_and_creates_no_shadow_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(activity, "observe_post") as post:
                receipt = self.receipt(root)
            self.assertEqual(receipt["result"], "DONE")
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*")),
                             [".agent-managed", ".agent-managed/runtime", ".agent-managed/runtime/dispatch-receipts.jsonl"])
            post.assert_not_called()

    def test_enabled_shadow_only_adds_decision_runtime_observation(self):
        manifest = {"decision": {"enabled": True, "audit_path": ".agent-managed/runtime/decision-audit.jsonl"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            correlation = activity.observe_pre(activity.DecisionConfig.from_manifest(manifest), {"objective": "x"}, audit=DecisionAudit(root, manifest["decision"]["audit_path"]))["correlation_id"]
            with patch.object(activity, "load_plan", return_value=PLAN):
                activity.record_receipt(root, "plan", "developer", "DONE", "model", None, None, None, None, [], manifest=manifest, correlation_id=correlation)
            files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
            self.assertEqual({p for p in files if "decision-observations/" not in p}, {
                ".agent-managed/runtime/dispatch-receipts.jsonl",
                ".agent-managed/runtime/decision-audit.jsonl",
            })
            self.assertEqual(len([p for p in files if "decision-observations/" in p]), 1)

    def test_enabled_lifecycle_uses_lookup_correlation_and_orphan_safe_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run([sys.executable, str(ROOT / "bin/agent-kit"), "init", "--profile", "generic", "--harness", "opencode"], cwd=root, check=True, capture_output=True)
            feature = root / ".specs/features/sample"
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text(
                "### T008: verify decision shadow lifecycle\n**Complexity**: LOW\n**Risk**: LOW\n",
                encoding="utf-8",
            )
            subprocess.run([sys.executable, str(ROOT / "state/state.py"), "new", "sample"], cwd=root, check=True, capture_output=True)
            manifest = {
                "harnesses": ["opencode"], "provider": {"default": "openai", "allowed": ["openai"], "strict": True},
                "decision": {"enabled": True, "mode": "shadow", "audit_path": ".agent-managed/runtime/decision-audit.jsonl"},
            }
            proposal = activity.create_proposal(root, manifest, "continue", "T008", "openai", "opencode")
            plan = activity.approve_proposal(root, proposal["proposalId"], [])
            receipt = activity.record_receipt(root, plan["planId"], "developer", "DONE", plan["roles"][1]["model"], 11, 7, 3, 5, [], manifest=manifest)
            audit = [json.loads(line) for line in (root / manifest["decision"]["audit_path"]).read_text().splitlines()]
            self.assertEqual(2, len(audit))
            self.assertEqual(audit[0]["correlationId"], audit[1]["correlationId"])
            self.assertEqual("sample", audit[0]["feature"])
            self.assertEqual("T008", audit[0]["task"])
            self.assertEqual("sample", audit[1]["feature"])
            self.assertEqual("T008", audit[1]["task"])
            self.assertEqual({"latencyMs": None, "inputTokens": 11, "outputTokens": 7, "cost": 3}, audit[1]["usage"])
            self.assertFalse(audit[1]["orphanedPreObservation"])
            self.assertEqual(receipt["kind"], "DispatchReceipt")
            lookup = json.loads((root / activity.DECISION_CORRELATIONS).read_text())
            self.assertIn(activity._decision_correlation_key(proposal), lookup)
            lookup_text = (root / activity.DECISION_CORRELATIONS).read_text()
            (root / activity.DECISION_CORRELATIONS).write_text("{}\n", encoding="utf-8")
            orphan_receipt = activity.record_receipt(root, plan["planId"], "developer", "DONE", plan["roles"][1]["model"], 11, 7, 3, 5, [], manifest=manifest)
            self.assertEqual(set(receipt), set(orphan_receipt))
            self.assertEqual({key: value for key, value in receipt.items() if key != "at"},
                             {key: value for key, value in orphan_receipt.items() if key != "at"})
            audit = [json.loads(line) for line in (root / manifest["decision"]["audit_path"]).read_text().splitlines()]
            self.assertEqual(3, len(audit))
            self.assertTrue(audit[2]["orphanedPreObservation"])
            self.assertEqual(("sample", "T008"), (audit[2]["feature"], audit[2]["task"]))
            self.assertRegex(audit[2]["correlationId"], r"^[0-9a-f]{20}$")
            self.assertNotEqual(audit[0]["correlationId"], audit[2]["correlationId"])
            (root / activity.DECISION_CORRELATIONS).write_text(lookup_text, encoding="utf-8")
            observation = next((root / ".agent-managed/runtime/decision-observations").glob("*.json"))
            observation.unlink()
            activity.record_receipt(root, plan["planId"], "developer", "DONE", plan["roles"][1]["model"], None, None, None, None, [], manifest=manifest)
            audit = [json.loads(line) for line in (root / manifest["decision"]["audit_path"]).read_text().splitlines()]
            self.assertTrue(audit[-1]["orphanedPreObservation"])

    def test_disabled_lifecycle_keeps_artifact_shapes_and_no_decision_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run([sys.executable, str(ROOT / "bin/agent-kit"), "init", "--profile", "generic", "--harness", "opencode"], cwd=root, check=True, capture_output=True)
            feature = root / ".specs/features/sample"
            feature.mkdir(parents=True)
            (feature / "tasks.md").write_text("### T008: disabled shadow\n**Complexity**: LOW\n**Risk**: LOW\n", encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "state/state.py"), "new", "sample"], cwd=root, check=True, capture_output=True)
            manifest = {"harnesses": ["opencode"], "decision": {"enabled": False}}
            proposal = activity.create_proposal(root, manifest, "continue", "T008", "openai", "opencode")
            plan = activity.approve_proposal(root, proposal["proposalId"], [])
            receipt = activity.record_receipt(root, plan["planId"], "developer", "DONE", plan["roles"][1]["model"], None, None, None, None, [], manifest=manifest)
            self.assertEqual({"ModelProposal", "DispatchPlan"}, {proposal["kind"], plan["kind"]})
            self.assertEqual("DispatchReceipt", receipt["kind"])
            runtime_files = {path.relative_to(root).as_posix() for path in (root / ".agent-managed/runtime").rglob("*") if path.is_file()}
            self.assertFalse(any("decision-" in path or "decision/" in path for path in runtime_files))


if __name__ == "__main__":
    unittest.main()
