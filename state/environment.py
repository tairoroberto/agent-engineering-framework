"""Portable local-environment diagnosis for the Agent Kit CLI.

The module deliberately owns no command-line parsing.  It returns compact,
secret-free facts so ``bin/agent-kit`` can render an interactive or JSON report
without duplicating dependency behavior.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path
import platform as platform_runtime
import shutil
import subprocess
from typing import Callable, Optional, Protocol, Sequence


class RequirementStatus(str, Enum):
    """A requirement outcome with enough detail to choose a safe repair."""

    OK = "ok"
    MISSING = "missing"
    NOT_RUNNING = "not_running"
    MISCONFIGURED = "misconfigured"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


@dataclass(frozen=True)
class CommandResult:
    """Bounded external-command result; output is never printed implicitly."""

    argv: tuple[str, ...]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None


class ProcessRunner(Protocol):
    """Small test seam for every external dependency interaction."""

    def run(self, argv: Sequence[str], *, timeout: float = 10) -> CommandResult: ...


class SubprocessRunner:
    """Production runner that turns process failures into values."""

    def run(self, argv: Sequence[str], *, timeout: float = 10) -> CommandResult:
        normalized = tuple(str(value) for value in argv)
        try:
            completed = subprocess.run(
                normalized,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            return CommandResult(
                normalized,
                None,
                stdout=error.stdout or "",
                stderr=error.stderr or "",
                timed_out=True,
                error=f"timed out after {timeout:g}s",
            )
        except OSError as error:
            return CommandResult(normalized, None, error=str(error))
        return CommandResult(
            normalized,
            completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class CheckResult:
    """One secret-free diagnostic fact within a requirement."""

    id: str
    label: str
    status: RequirementStatus
    detail: str | None = None
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status.value,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass(frozen=True)
class RepairAction:
    """A pre-classified, known action shown before any machine mutation."""

    id: str
    description: str
    requirement_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "description": self.description,
            "requirementId": self.requirement_id,
        }


@dataclass(frozen=True)
class OperationResult:
    """One authorized repair operation, retained for the final report."""

    action_id: str
    succeeded: bool
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "actionId": self.action_id,
            "succeeded": self.succeeded,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RequirementResult:
    """Aggregate status, checks, and permitted actions for one requirement."""

    id: str
    name: str
    description: str
    required: bool
    status: RequirementStatus
    checks: tuple[CheckResult, ...] = ()
    actions: tuple[RepairAction, ...] = ()
    version: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "status": self.status.value,
            "version": self.version,
            "checks": [check.to_dict() for check in self.checks],
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class PlatformInfo:
    """Host facts intentionally limited to values relevant to installation."""

    system: str
    architecture: str
    node_version: str | None = None
    npm_version: str | None = None
    npx_version: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "os": self.system.lower(),
            "architecture": self.architecture,
            "node": self.node_version,
            "npm": self.npm_version,
            "npx": self.npx_version,
        }


@dataclass(frozen=True)
class EnvironmentReport:
    """Full immutable diagnosis returned by one inspection pass."""

    platform: PlatformInfo
    requirements: tuple[RequirementResult, ...]
    harnesses: tuple[CheckResult, ...] = ()
    operations: tuple[OperationResult, ...] = ()

    @property
    def healthy(self) -> bool:
        return all(
            not requirement.required or requirement.status == RequirementStatus.OK
            for requirement in self.requirements
        )

    @property
    def actions(self) -> tuple[RepairAction, ...]:
        return tuple(action for requirement in self.requirements for action in requirement.actions)

    def to_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "platform": self.platform.to_dict(),
            "requirements": [requirement.to_dict() for requirement in self.requirements],
            "harnesses": [harness.to_dict() for harness in self.harnesses],
            "operations": [operation.to_dict() for operation in self.operations],
        }


ExecutableFinder = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class EnvironmentContext:
    """Explicit dependencies make diagnostics deterministic and testable."""

    root: Path
    home: Path
    runner: ProcessRunner
    system: str
    architecture: str
    executable_finder: ExecutableFinder = shutil.which

    @classmethod
    def current(cls, root: Path, *, runner: ProcessRunner | None = None) -> "EnvironmentContext":
        return cls(
            root=root.resolve(),
            home=Path.home(),
            runner=runner or SubprocessRunner(),
            system=platform_runtime.system(),
            architecture=platform_runtime.machine(),
        )


class EnvironmentRequirement(ABC):
    """Independent requirement contract; implementations are added to one list."""

    id: str
    name: str
    description: str
    required: bool = True

    @abstractmethod
    def diagnose(self, context: EnvironmentContext, platform: PlatformInfo) -> RequirementResult:
        """Return facts and known actions without changing the host."""

    def repair(
        self,
        context: EnvironmentContext,
        platform: PlatformInfo,
        action_ids: set[str],
    ) -> tuple[OperationResult, ...]:
        """Run only actions selected from the preceding report."""
        return ()


def requirement_status(checks: Sequence[CheckResult]) -> RequirementStatus:
    """Derive a stable aggregate status without treating optional checks as faults."""
    required_checks = [check for check in checks if check.required]
    if not required_checks or all(check.status == RequirementStatus.OK for check in required_checks):
        return RequirementStatus.OK
    statuses = {check.status for check in required_checks}
    if RequirementStatus.ERROR in statuses:
        return RequirementStatus.ERROR
    if RequirementStatus.UNSUPPORTED in statuses:
        return RequirementStatus.UNSUPPORTED
    if RequirementStatus.NOT_RUNNING in statuses and len(statuses) == 1:
        return RequirementStatus.NOT_RUNNING
    if RequirementStatus.MISSING in statuses and len(statuses) == 1:
        return RequirementStatus.MISSING
    if RequirementStatus.MISCONFIGURED in statuses and len(statuses) == 1:
        return RequirementStatus.MISCONFIGURED
    return RequirementStatus.PARTIAL


def command_version(context: EnvironmentContext, executable: str) -> str | None:
    """Read a CLI version without surfacing command output to the report."""
    result = context.runner.run((executable, "--version"))
    if not result.succeeded:
        return None
    value = result.stdout.strip().splitlines()
    return value[0] if value else None


class EnvironmentService:
    """Coordinates independent requirements while retaining partial evidence."""

    def __init__(self, context: EnvironmentContext, requirements: Sequence[EnvironmentRequirement]) -> None:
        self.context = context
        self.requirements = tuple(requirements)

    def inspect(self) -> EnvironmentReport:
        platform = inspect_platform(self.context)
        results: list[RequirementResult] = []
        for requirement in self.requirements:
            try:
                results.append(requirement.diagnose(self.context, platform))
            except Exception as error:  # pragma: no cover - safety boundary for third-party probes
                results.append(RequirementResult(
                    id=requirement.id,
                    name=requirement.name,
                    description=requirement.description,
                    required=requirement.required,
                    status=RequirementStatus.ERROR,
                    checks=(CheckResult(
                        id="diagnostic",
                        label="diagnostic",
                        status=RequirementStatus.ERROR,
                        detail=type(error).__name__,
                    ),),
                ))
        return EnvironmentReport(platform=platform, requirements=tuple(results))

    def repair(self, report: EnvironmentReport) -> tuple[OperationResult, ...]:
        platform = report.platform
        requested = {action.id for action in report.actions}
        operations: list[OperationResult] = []
        for requirement in self.requirements:
            try:
                operations.extend(requirement.repair(self.context, platform, requested))
            except Exception as error:  # pragma: no cover - safety boundary for third-party repair
                operations.append(OperationResult(
                    action_id=f"{requirement.id}:repair",
                    succeeded=False,
                    detail=type(error).__name__,
                ))
        return tuple(operations)


def inspect_platform(context: EnvironmentContext) -> PlatformInfo:
    """Collect Node tooling independently so one missing binary is visible."""
    versions: dict[str, str | None] = {}
    for tool in ("node", "npm", "npx"):
        path = context.executable_finder(tool)
        versions[tool] = command_version(context, path) if path else None
    return PlatformInfo(
        system=context.system,
        architecture=context.architecture,
        node_version=versions["node"],
        npm_version=versions["npm"],
        npx_version=versions["npx"],
    )
