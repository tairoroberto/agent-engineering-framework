"""Portable local-environment diagnosis for the Agent Kit CLI.

The module deliberately owns no command-line parsing.  It returns compact,
secret-free facts so ``bin/agent-kit`` can render an interactive or JSON report
without duplicating dependency behavior.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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


AI_MEMORY_LABEL = "com.github.akitaonrails.ai-memory"
AI_MEMORY_HTTP_URL = "http://127.0.0.1:49374/mcp"


def detected_harnesses(context: EnvironmentContext, names: Sequence[str]) -> tuple[CheckResult, ...]:
    """Return optional harness facts, leaving requirements to own their checks."""
    results: list[CheckResult] = []
    for name in names:
        executable = context.executable_finder(name)
        results.append(CheckResult(
            id=name,
            label=name.title(),
            status=RequirementStatus.OK if executable else RequirementStatus.MISSING,
            detail=executable or "not found in PATH",
            required=False,
        ))
    return tuple(results)


def ai_memory_data_dir(context: EnvironmentContext) -> Path:
    """Use the native default while respecting an explicit local override."""
    configured = os.environ.get("AI_MEMORY_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if context.system.lower() == "darwin":
        return context.home / "Library" / "Application Support" / "ai-memory"
    if context.system.lower() == "windows":
        return Path(os.environ.get("LOCALAPPDATA", str(context.home / "AppData" / "Local"))) / "ai-memory"
    return Path(os.environ.get("XDG_DATA_HOME", str(context.home / ".local" / "share"))) / "ai-memory"


def safe_file_contains(path: Path, value: str) -> bool:
    """Check a capability marker without returning user-owned config content."""
    try:
        return path.is_file() and value.lower() in path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeError):
        return False


class AiMemoryRequirement(EnvironmentRequirement):
    """Diagnose native ai-memory health and supported harness capabilities."""

    id = "ai-memory"
    name = "ai-memory"
    description = "Local memory binary, service, and harness integrations"

    def __init__(self, harnesses: Sequence[str]) -> None:
        self.harnesses = tuple(harnesses)

    def diagnose(self, context: EnvironmentContext, platform: PlatformInfo) -> RequirementResult:
        binary = self._binary(context)
        checks: list[CheckResult] = []
        if binary is None:
            checks.append(CheckResult("binary", "binary", RequirementStatus.MISSING, "not found"))
            checks.append(CheckResult("initialized", "initialized", RequirementStatus.MISSING, "binary unavailable"))
            checks.append(CheckResult("service", "service", RequirementStatus.MISSING, "binary unavailable"))
            checks.extend(self._integration_checks(context, available=False))
            actions = self._missing_actions(platform)
            return RequirementResult(
                id=self.id,
                name=self.name,
                description=self.description,
                required=True,
                status=requirement_status(checks),
                checks=tuple(checks),
                actions=actions,
            )

        version = command_version(context, binary)
        checks.append(CheckResult(
            "binary",
            "binary",
            RequirementStatus.OK if version else RequirementStatus.ERROR,
            binary,
        ))
        checks.append(self._initialized_check(context))
        checks.extend(self._service_checks(context, binary))
        checks.extend(self._integration_checks(context, available=True))
        actions = self._repair_actions(context, platform, checks)
        return RequirementResult(
            id=self.id,
            name=self.name,
            description=self.description,
            required=True,
            status=requirement_status(checks),
            checks=tuple(checks),
            actions=actions,
            version=version,
        )

    def _binary(self, context: EnvironmentContext) -> str | None:
        found = context.executable_finder("ai-memory")
        canonical = context.home / "Applications" / "ai-memory" / "ai-memory"
        if canonical.is_file() and os.access(canonical, os.X_OK):
            return str(canonical)
        return found

    def _initialized_check(self, context: EnvironmentContext) -> CheckResult:
        data_dir = ai_memory_data_dir(context)
        initialized = (data_dir / "config.toml").is_file()
        return CheckResult(
            "initialized",
            "initialized",
            RequirementStatus.OK if initialized else RequirementStatus.MISSING,
            str(data_dir) if initialized else "data configuration missing",
        )

    def _service_checks(self, context: EnvironmentContext, binary: str) -> tuple[CheckResult, ...]:
        status = context.runner.run((binary, "status"))
        status_output = (status.stdout + "\n" + status.stderr).lower()
        if status.succeeded:
            cli = CheckResult("cli", "CLI status", RequirementStatus.OK, "communicating")
        elif status.error or status.timed_out:
            cli = CheckResult("cli", "CLI status", RequirementStatus.ERROR, status.error or "timed out")
        elif any(token in status_output for token in ("not initialized", "data directory", "config.toml")):
            cli = CheckResult("cli", "CLI status", RequirementStatus.MISSING, "not initialized")
        else:
            cli = CheckResult("cli", "CLI status", RequirementStatus.NOT_RUNNING, "server unavailable")
        return (*self._launchd_checks(context), self._http_check(context), cli)

    def _launchd_checks(self, context: EnvironmentContext) -> tuple[CheckResult, ...]:
        if context.system.lower() != "darwin":
            return (CheckResult(
                "launchd",
                "launchd",
                RequirementStatus.UNSUPPORTED,
                "not applicable outside macOS",
                required=False,
            ),)
        launchctl = context.executable_finder("launchctl") or "launchctl"
        domain = f"gui/{os.getuid()}/{AI_MEMORY_LABEL}"
        result = context.runner.run((launchctl, "print", domain))
        if result.succeeded and "state = running" in result.stdout.lower():
            return (CheckResult("launchd", "launchd", RequirementStatus.OK, "running"),)
        if result.succeeded:
            return (CheckResult("launchd", "launchd", RequirementStatus.NOT_RUNNING, "registered but not running"),)
        if result.error or result.timed_out:
            return (CheckResult("launchd", "launchd", RequirementStatus.ERROR, result.error or "timed out"),)
        return (CheckResult("launchd", "launchd", RequirementStatus.MISSING, "not registered"),)

    def _http_check(self, context: EnvironmentContext) -> CheckResult:
        curl = context.executable_finder("curl")
        if not curl:
            return CheckResult("http", "HTTP server", RequirementStatus.ERROR, "curl unavailable")
        result = context.runner.run((
            curl, "--silent", "--show-error", "--output", os.devnull,
            "--write-out", "%{http_code}", AI_MEMORY_HTTP_URL,
        ))
        code = result.stdout.strip()
        if code in {"200", "401", "405"}:
            return CheckResult("http", "HTTP server", RequirementStatus.OK, f"HTTP {code}")
        if result.error or result.timed_out:
            return CheckResult("http", "HTTP server", RequirementStatus.ERROR, result.error or "timed out")
        return CheckResult("http", "HTTP server", RequirementStatus.NOT_RUNNING, f"HTTP {code or 'unavailable'}")

    def _integration_checks(self, context: EnvironmentContext, *, available: bool) -> tuple[CheckResult, ...]:
        checks: list[CheckResult] = []
        for harness in self.harnesses:
            executable = context.executable_finder(harness)
            if not executable:
                continue
            if not available:
                checks.append(CheckResult(
                    f"{harness}-mcp", f"{harness.title()} MCP", RequirementStatus.MISSING, "ai-memory unavailable",
                ))
                if harness != "copilot":
                    checks.append(CheckResult(
                        f"{harness}-hooks", f"{harness.title()} hooks", RequirementStatus.MISSING, "ai-memory unavailable",
                    ))
                continue
            checks.extend(self._harness_checks(context, harness))
        return tuple(checks)

    def _harness_checks(self, context: EnvironmentContext, harness: str) -> tuple[CheckResult, ...]:
        if harness == "codex":
            config = context.home / ".codex" / "config.toml"
            mcp = safe_file_contains(config, "[mcp_servers.ai-memory]")
            hooks = safe_file_contains(config, "ai-memory") and safe_file_contains(config, "hook")
            return (
                CheckResult("codex-mcp", "Codex MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("codex-hooks", "Codex hooks", RequirementStatus.OK if hooks else RequirementStatus.MISSING, "configured" if hooks else "missing"),
            )
        if harness == "opencode":
            config = context.home / ".config" / "opencode" / "opencode.json"
            plugin = context.home / ".config" / "opencode" / "plugins" / "ai-memory.ts"
            mcp = safe_file_contains(config, "ai-memory")
            hooks = safe_file_contains(plugin, "ai-memory")
            return (
                CheckResult("opencode-mcp", "OpenCode MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("opencode-hooks", "OpenCode lifecycle", RequirementStatus.OK if hooks else RequirementStatus.MISSING, "configured" if hooks else "missing"),
            )
        if harness == "copilot":
            config = context.root / ".vscode" / "mcp.json"
            mcp = safe_file_contains(config, "ai-memory")
            return (
                CheckResult("copilot-mcp", "Copilot MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("copilot-hooks", "Copilot hooks", RequirementStatus.UNSUPPORTED, "MCP only", required=False),
            )
        return ()

    def _missing_actions(self, platform: PlatformInfo) -> tuple[RepairAction, ...]:
        if platform.system.lower() != "darwin":
            return ()
        if architecture_artifact(platform.architecture) is None:
            return ()
        return (RepairAction(
            "ai-memory:install",
            "Download ai-memory from akitaonrails/ai-memory and configure its LaunchAgent",
            self.id,
        ),)

    def _repair_actions(
        self,
        context: EnvironmentContext,
        platform: PlatformInfo,
        checks: Sequence[CheckResult],
    ) -> tuple[RepairAction, ...]:
        by_id = {check.id: check for check in checks}
        actions: list[RepairAction] = []
        if platform.system.lower() == "darwin" and any(
            by_id[name].status != RequirementStatus.OK
            for name in ("launchd", "http", "cli")
            if name in by_id
        ):
            actions.append(RepairAction(
                "ai-memory:service",
                "Repair ai-memory LaunchAgent and local service",
                self.id,
            ))
        for harness in ("codex", "opencode", "copilot"):
            if f"{harness}-mcp" in by_id and by_id[f"{harness}-mcp"].status != RequirementStatus.OK:
                actions.append(RepairAction(
                    f"ai-memory:{harness}-mcp",
                    f"Configure ai-memory MCP for {harness.title()}",
                    self.id,
                ))
            if harness != "copilot" and f"{harness}-hooks" in by_id and by_id[f"{harness}-hooks"].status != RequirementStatus.OK:
                actions.append(RepairAction(
                    f"ai-memory:{harness}-hooks",
                    f"Configure ai-memory lifecycle integration for {harness.title()}",
                    self.id,
                ))
        return tuple(actions)


def architecture_artifact(architecture: str) -> str | None:
    """Translate macOS architecture facts to the official release suffix."""
    normalized = architecture.lower()
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    if normalized == "x86_64":
        return "x86_64"
    return None
