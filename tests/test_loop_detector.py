import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state.loop_detector import LoopDetector, LoopLimits


class LoopDetectorTest(unittest.TestCase):
    def test_detects_all_deterministic_signals(self):
        history = [
            {"retry_count": 3, "command": "c", "error": "e", "source": "s", "gate": "g", "state": "a", "meaningful_progress": True},
            {"command": "c", "error": "e", "source": "s", "gate": "g", "state": "b"},
            {"command": "c", "error": "e", "source": "s", "gate": "g", "state": "a"},
        ]
        finding = LoopDetector().evaluate(history)
        self.assertEqual(("retry_ceiling", "repeated_command", "repeated_error", "repeated_source", "unchanged_source", "oscillation", "repeated_gate"), finding.signals)
        self.assertTrue(finding.looping)
        self.assertTrue(finding.advisory_progress)

    def test_window_boundary_does_not_trigger(self):
        finding = LoopDetector().evaluate([{"command": "x"}, {"command": "x"}], LoopLimits(command_window=3))
        self.assertEqual((), finding.signals)

    def test_output_is_stable_and_progress_cannot_clear_finding(self):
        history = [{"source": "same", "meaningful_progress": True}] * 3
        first = LoopDetector().evaluate(history)
        second = LoopDetector().evaluate(history)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertIn("unchanged_source", first.signals)

    def test_oscillation_scans_any_triple_in_recent_window(self):
        history = [{"state": "a", "source": "1"}, {"state": "b", "source": "2"}, {"state": "c", "source": "3"}, {"state": "b", "source": "4"}, {"state": "c", "source": "5"}]
        finding = LoopDetector().evaluate(history, LoopLimits(oscillation_window=5))
        self.assertEqual(("oscillation",), finding.signals)

    def test_oscillation_requires_complete_recent_window(self):
        finding = LoopDetector().evaluate([{"state": "a", "source": "1"}, {"state": "b", "source": "2"}, {"state": "a", "source": "3"}], LoopLimits(oscillation_window=4))
        self.assertEqual((), finding.signals)

    def test_invalid_meaningful_progress_is_normalized_to_none(self):
        finding = LoopDetector().evaluate([{"meaningful_progress": "yes"}, {"meaningful_progress": 1}])
        self.assertIsNone(finding.advisory_progress)

    def test_meaningful_progress_accepts_only_bool(self):
        self.assertTrue(LoopDetector().evaluate([{"meaningful_progress": True}]).advisory_progress)
        self.assertFalse(LoopDetector().evaluate([{"meaningful_progress": False}]).advisory_progress)

    def test_oscillation_ignores_absent_null_and_invalid_states(self):
        history = [
            {"state": "a"},
            {},
            {"state": None},
            {"state": 1},
            {"state": "b"},
            {"state": "a"},
        ]
        self.assertIn("oscillation", LoopDetector().evaluate(history).signals)

    def test_oscillation_rejects_invalid_values_without_two_named_states(self):
        history = [{"state": "a"}, {"state": None}, {"state": "a"}, {"state": 2}]
        self.assertNotIn("oscillation", LoopDetector().evaluate(history).signals)

    def test_each_signal_has_negative_and_finite_window_boundary(self):
        cases = (
            ("retry_ceiling", [{"retry_count": 2}], [{"retry_count": 3}], LoopLimits(retry_ceiling=3)),
            ("repeated_command", [{"command": "x"}] * 2, [{"command": "x"}] * 3, LoopLimits(command_window=3)),
            ("repeated_error", [{"error": "x"}] * 2, [{"error": "x"}] * 3, LoopLimits(error_window=3)),
            ("repeated_source", [{"source": "x"}] * 2, [{"source": "x"}] * 3, LoopLimits(source_window=3)),
            ("repeated_gate", [{"gate": "x"}] * 2, [{"gate": "x"}] * 3, LoopLimits(gate_window=3)),
            ("unchanged_source", [{"source": "x"}] * 2, [{"source": "x"}] * 3, LoopLimits(no_progress_window=3)),
            ("oscillation", [{"state": "a"}, {"state": "b"}], [{"state": "a"}, {"state": "b"}, {"state": "a"}], LoopLimits(oscillation_window=3)),
        )
        for signal, negative, positive, limits in cases:
            self.assertNotIn(signal, LoopDetector().evaluate(negative, limits).signals, signal)
            self.assertIn(signal, LoopDetector().evaluate(positive, limits).signals, signal)

    def test_repeated_values_require_non_null_and_no_progress_is_advisory(self):
        self.assertNotIn("repeated_command", LoopDetector().evaluate([{"command": None}] * 3).signals)
        self.assertFalse(LoopDetector().evaluate([{"meaningful_progress": False}]).advisory_progress)
        self.assertIsNone(LoopDetector().evaluate([{}]).advisory_progress)


if __name__ == "__main__":
    unittest.main()
