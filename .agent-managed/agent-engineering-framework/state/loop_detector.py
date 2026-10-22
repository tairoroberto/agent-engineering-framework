"""Pure, bounded detection of deterministic execution loops."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class LoopLimits:
    """Finite windows and ceilings used by :class:`LoopDetector`."""

    retry_ceiling: int = 3
    command_window: int = 3
    error_window: int = 3
    source_window: int = 3
    gate_window: int = 3
    no_progress_window: int = 3
    oscillation_window: int = 3


@dataclass(frozen=True)
class LoopFinding:
    """Stable result: signals are ordered and facts contain no raw payloads."""

    looping: bool
    signals: tuple[str, ...]
    advisory_progress: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "looping": self.looping,
            "signals": list(self.signals),
            "advisoryProgress": self.advisory_progress,
        }


class LoopDetector:
    """Evaluate compact history facts without reading state, Git, or the clock."""

    SIGNALS = (
        "retry_ceiling",
        "repeated_command",
        "repeated_error",
        "repeated_source",
        "unchanged_source",
        "oscillation",
        "repeated_gate",
    )

    def evaluate(self, history: Iterable[Mapping[str, Any]], limits: LoopLimits | None = None) -> LoopFinding:
        limits = limits or LoopLimits()
        entries = tuple(history)
        signals: list[str] = []

        retry = [e.get("retry_count", e.get("retryCount")) for e in entries]
        if any(isinstance(value, int) and not isinstance(value, bool) and value >= limits.retry_ceiling for value in retry):
            signals.append("retry_ceiling")

        checks = (
            ("command", limits.command_window, "repeated_command"),
            ("error", limits.error_window, "repeated_error"),
            ("source", limits.source_window, "repeated_source"),
            ("gate", limits.gate_window, "repeated_gate"),
        )
        for key, window, signal in checks:
            values = _values(entries, key)
            if window > 0 and len(values) >= window and _repeated(values[-window:]):
                signals.append(signal)

        sources = _values(entries, "source")
        if limits.no_progress_window > 0 and len(sources) >= limits.no_progress_window:
            if len(set(sources[-limits.no_progress_window:])) == 1:
                signals.append("unchanged_source")

        states = [value for value in _values(entries, "state") if _valid_state(value)]
        if limits.oscillation_window >= 3 and len(states) >= limits.oscillation_window:
            window = states[-limits.oscillation_window:]
            if any(left == right and left != middle for left, middle, right in zip(window, window[1:], window[2:])):
                signals.append("oscillation")

        advisory = _advisory_progress(entries)
        return LoopFinding(bool(signals), tuple(signal for signal in self.SIGNALS if signal in signals), advisory)


def evaluate(history: Iterable[Mapping[str, Any]], limits: LoopLimits | None = None) -> LoopFinding:
    return LoopDetector().evaluate(history, limits)


def _values(entries: tuple[Mapping[str, Any], ...], key: str) -> list[Any]:
    aliases = {"command": ("command", "command_fingerprint"), "error": ("error", "error_fingerprint"),
               "source": ("source", "source_fingerprint", "diff_fingerprint"), "gate": ("gate", "gate_fingerprint"),
               "state": ("state", "status")}
    names = aliases[key]
    return [next((entry[name] for name in names if name in entry), None) for entry in entries]


def _repeated(values: list[Any]) -> bool:
    return values[0] is not None and len(Counter(map(repr, values))) == 1


def _valid_state(value: Any) -> bool:
    """Only named states can participate in an A-B-A signal."""
    return isinstance(value, str) and bool(value.strip())


def _advisory_progress(entries: tuple[Mapping[str, Any], ...]) -> bool | None:
    values = [entry.get("meaningful_progress") for entry in entries if "meaningful_progress" in entry]
    if not values:
        return None
    value = values[-1]
    return value if isinstance(value, bool) else None
