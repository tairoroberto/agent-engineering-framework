"""Portable local-environment diagnosis for the Agent Kit CLI.

The module deliberately owns no command-line parsing.  It returns compact,
secret-free facts so ``bin/agent-kit`` can render an interactive or JSON report
without duplicating dependency behavior.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import platform as platform_runtime
import shutil
import subprocess
import tempfile
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
    preview: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "description": self.description,
            "requirementId": self.requirement_id,
            "preview": list(self.preview),
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

    def __init__(
        self,
        context: EnvironmentContext,
        requirements: Sequence[EnvironmentRequirement],
        *,
        harnesses: Sequence[str] = (),
    ) -> None:
        self.context = context
        self.requirements = tuple(requirements)
        self.harnesses = tuple(harnesses)

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
        return EnvironmentReport(
            platform=platform,
            requirements=tuple(results),
            harnesses=detected_harnesses(self.context, self.harnesses),
        )

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


class NodeToolingRequirement(EnvironmentRequirement):
    """Report the Node toolchain without attempting a system-level install."""

    id = "node-tooling"
    name = "Node.js toolchain"
    description = "Node.js, npm, and npx required by globally managed skills"

    def diagnose(self, context: EnvironmentContext, platform: PlatformInfo) -> RequirementResult:
        versions = (
            ("node", "Node.js", platform.node_version),
            ("npm", "npm", platform.npm_version),
            ("npx", "npx", platform.npx_version),
        )
        checks = tuple(CheckResult(
            identifier,
            label,
            RequirementStatus.OK if version else RequirementStatus.MISSING,
            version or "not found in PATH; install Node.js outside agent-kit",
        ) for identifier, label, version in versions)
        return RequirementResult(
            id=self.id,
            name=self.name,
            description=self.description,
            required=True,
            status=requirement_status(checks),
            checks=checks,
        )


AI_MEMORY_LABEL = "com.github.akitaonrails.ai-memory"
AI_MEMORY_HTTP_URL = "http://127.0.0.1:49374/mcp"
AI_MEMORY_RELEASE_URL = "https://github.com/akitaonrails/ai-memory/releases/latest/download/ai-memory-macos-{architecture}.tar.gz"
AI_MEMORY_LAUNCH_AGENT = "com.github.akitaonrails.ai-memory.plist"


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


def json_mcp_server_configured(path: Path, *, top_level_servers: bool = False) -> bool:
    """Recognize a named MCP server structurally without exposing config values."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if top_level_servers:
        servers = data.get("servers")
        return isinstance(servers, dict) and "ai-memory" in servers
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return False
    if "ai-memory" in mcp:
        return True
    servers = mcp.get("servers")
    return isinstance(servers, dict) and "ai-memory" in servers


def json_codex_ai_memory_hooks_configured(path: Path) -> bool:
    """Recognize an ai-memory command inside Codex's nested hooks schema."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return False
    for registrations in hooks.values():
        if not isinstance(registrations, list):
            continue
        for registration in registrations:
            nested = registration.get("hooks") if isinstance(registration, dict) else None
            if not isinstance(nested, list):
                continue
            for hook in nested:
                command = hook.get("command") if isinstance(hook, dict) else None
                normalized = command.lower() if isinstance(command, str) else ""
                if "ai-memory" in normalized and "hook" in normalized:
                    return True
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
            checks.append(self._automatic_install_check(platform))
            checks.extend(self._integration_checks(context, available=False))
            actions = self._missing_actions(context, platform)
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

    def repair(
        self,
        context: EnvironmentContext,
        platform: PlatformInfo,
        action_ids: set[str],
    ) -> tuple[OperationResult, ...]:
        operations: list[OperationResult] = []
        binary = self._binary(context)
        if "ai-memory:install" in action_ids:
            installed = self._install_macos(context, platform)
            operations.append(installed)
            if not installed.succeeded:
                return tuple(operations)
            binary = self._binary(context)
            if binary is None:
                return tuple((*operations, OperationResult(
                    "ai-memory:install", False, "installed binary was not discoverable",
                )))
            operations.append(self._configure_launchd(context, binary))
            operations.extend(self._configure_detected_integrations(context, binary))
            return tuple(operations)
        if binary is None:
            return ()
        if "ai-memory:service" in action_ids:
            operations.append(self._configure_launchd(context, binary))
        for harness in ("codex", "opencode", "copilot"):
            if f"ai-memory:{harness}-mcp" in action_ids:
                operations.append(self._configure_integration(context, binary, harness, "mcp"))
            if harness != "copilot" and f"ai-memory:{harness}-hooks" in action_ids:
                operations.append(self._configure_integration(context, binary, harness, "hooks"))
        return tuple(operations)

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
            hooks_config = context.home / ".codex" / "hooks.json"
            mcp = safe_file_contains(config, "[mcp_servers.ai-memory]")
            hooks = json_codex_ai_memory_hooks_configured(hooks_config)
            return (
                CheckResult("codex-mcp", "Codex MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("codex-hooks", "Codex hooks", RequirementStatus.OK if hooks else RequirementStatus.MISSING, "configured" if hooks else "missing"),
            )
        if harness == "opencode":
            config = context.home / ".config" / "opencode" / "opencode.json"
            plugin = context.home / ".config" / "opencode" / "plugins" / "ai-memory.ts"
            mcp = json_mcp_server_configured(config)
            hooks = safe_file_contains(plugin, "ai-memory")
            return (
                CheckResult("opencode-mcp", "OpenCode MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("opencode-hooks", "OpenCode lifecycle", RequirementStatus.OK if hooks else RequirementStatus.MISSING, "configured" if hooks else "missing"),
            )
        if harness == "copilot":
            config = context.root / ".vscode" / "mcp.json"
            mcp = json_mcp_server_configured(config, top_level_servers=True)
            return (
                CheckResult("copilot-mcp", "Copilot MCP", RequirementStatus.OK if mcp else RequirementStatus.MISSING, "configured" if mcp else "missing"),
                CheckResult("copilot-hooks", "Copilot hooks", RequirementStatus.UNSUPPORTED, "MCP only", required=False),
            )
        return ()

    def _missing_actions(
        self,
        context: EnvironmentContext,
        platform: PlatformInfo,
    ) -> tuple[RepairAction, ...]:
        if platform.system.lower() != "darwin":
            return ()
        if architecture_artifact(platform.architecture) is None:
            return ()
        binary = context.home / "Applications" / "ai-memory" / "ai-memory"
        preview = [
            f"download {AI_MEMORY_RELEASE_URL.format(architecture=architecture_artifact(platform.architecture))}",
            f"{binary} init",
            f"launchctl print gui/{os.getuid()}/{AI_MEMORY_LABEL}",
            f"launchctl bootstrap gui/{os.getuid()} {context.home / 'Library' / 'LaunchAgents' / AI_MEMORY_LAUNCH_AGENT}",
        ]
        for harness in self.harnesses:
            if not context.executable_finder(harness) or harness not in {"codex", "opencode", "copilot"}:
                continue
            preview.extend(self._integration_preview(context, str(binary), harness, "mcp"))
            if harness != "copilot":
                preview.extend(self._integration_preview(context, str(binary), harness, "hooks"))
        return (RepairAction(
            "ai-memory:install",
            "Download ai-memory from akitaonrails/ai-memory, initialize it, configure its LaunchAgent, and wire detected harnesses",
            self.id,
            tuple(preview),
        ),)

    def _automatic_install_check(self, platform: PlatformInfo) -> CheckResult:
        if platform.system.lower() != "darwin":
            return CheckResult(
                "automatic-install",
                "automatic installation",
                RequirementStatus.UNSUPPORTED,
                "automatic ai-memory installation is available only on macOS",
                required=False,
            )
        architecture = architecture_artifact(platform.architecture)
        if architecture is None:
            return CheckResult(
                "automatic-install",
                "automatic installation",
                RequirementStatus.UNSUPPORTED,
                f"unsupported macOS architecture: {platform.architecture}",
                required=False,
            )
        return CheckResult(
            "automatic-install",
            "automatic installation",
            RequirementStatus.OK,
            f"macOS {architecture} release available after approval",
            required=False,
        )

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
                (
                    f"launchctl print gui/{os.getuid()}/{AI_MEMORY_LABEL}",
                    f"launchctl bootout gui/{os.getuid()}/{AI_MEMORY_LABEL} (only if registered)",
                    f"launchctl bootstrap gui/{os.getuid()} {context.home / 'Library' / 'LaunchAgents' / AI_MEMORY_LAUNCH_AGENT}",
                ),
            ))
        for harness in ("codex", "opencode", "copilot"):
            if f"{harness}-mcp" in by_id and by_id[f"{harness}-mcp"].status != RequirementStatus.OK:
                actions.append(RepairAction(
                    f"ai-memory:{harness}-mcp",
                    f"Configure ai-memory MCP for {harness.title()}",
                    self.id,
                    self._integration_preview(context, self._binary(context) or "ai-memory", harness, "mcp"),
                ))
            if harness != "copilot" and f"{harness}-hooks" in by_id and by_id[f"{harness}-hooks"].status != RequirementStatus.OK:
                actions.append(RepairAction(
                    f"ai-memory:{harness}-hooks",
                    f"Configure ai-memory lifecycle integration for {harness.title()}",
                    self.id,
                    self._integration_preview(context, self._binary(context) or "ai-memory", harness, "hooks"),
                ))
        return tuple(actions)

    def _integration_preview(
        self,
        context: EnvironmentContext,
        binary: str,
        harness: str,
        capability: str,
    ) -> tuple[str, ...]:
        if capability == "mcp":
            client = "vscode-copilot" if harness == "copilot" else harness
            command = f"{binary} install-mcp --client {client} --apply"
            if harness == "copilot":
                command += f" --config-file {context.root / '.vscode' / 'mcp.json'}"
            return (command,)
        return (f"{binary} install-hooks --agent {harness} --apply",)

    def _install_macos(self, context: EnvironmentContext, platform: PlatformInfo) -> OperationResult:
        if platform.system.lower() != "darwin":
            return OperationResult("ai-memory:install", False, "automatic installation is supported only on macOS")
        architecture = architecture_artifact(platform.architecture)
        if architecture is None:
            return OperationResult("ai-memory:install", False, f"unsupported architecture: {platform.architecture}")
        curl = context.executable_finder("curl")
        tar = context.executable_finder("tar") or "tar"
        if not curl:
            return OperationResult("ai-memory:install", False, "curl unavailable")
        url = AI_MEMORY_RELEASE_URL.format(architecture=architecture)
        try:
            with tempfile.TemporaryDirectory(prefix="agent-kit-ai-memory-") as raw:
                staging = Path(raw)
                archive = staging / "ai-memory.tar.gz"
                downloaded = context.runner.run((
                    curl, "--fail", "--location", "--silent", "--show-error",
                    "--output", str(archive), url,
                ), timeout=120)
                if not downloaded.succeeded:
                    return OperationResult("ai-memory:install", False, command_failure(downloaded))
                extracted = staging / "extracted"
                extracted.mkdir()
                unpacked = context.runner.run((tar, "-xzf", str(archive), "-C", str(extracted)), timeout=120)
                if not unpacked.succeeded:
                    return OperationResult("ai-memory:install", False, command_failure(unpacked))
                binary, distribution = extracted_ai_memory_distribution(extracted)
                if binary is None or distribution is None:
                    return OperationResult("ai-memory:install", False, "release archive lacks ai-memory binary or launchd template")
                target_dir = context.home / "Applications" / "ai-memory"
                target_dir.mkdir(parents=True, exist_ok=True)
                for source in distribution.iterdir():
                    target = target_dir / source.name
                    if source.is_dir():
                        shutil.copytree(source, target, dirs_exist_ok=True)
                    elif source.name != "ai-memory":
                        shutil.copy2(source, target)
                target_binary = target_dir / "ai-memory"
                temporary_binary = target_dir / ".agent-kit-ai-memory"
                shutil.copy2(binary, temporary_binary)
                temporary_binary.chmod(temporary_binary.stat().st_mode | 0o111)
                os.replace(temporary_binary, target_binary)
                initialized = context.runner.run((str(target_binary), "init"), timeout=30)
                if not initialized.succeeded:
                    return OperationResult("ai-memory:install", False, command_failure(initialized))
        except OSError as error:
            return OperationResult("ai-memory:install", False, str(error))
        return OperationResult("ai-memory:install", True, f"installed macOS {architecture} release")

    def _configure_launchd(self, context: EnvironmentContext, binary: str) -> OperationResult:
        if context.system.lower() != "darwin":
            return OperationResult("ai-memory:service", False, "LaunchAgent repair is supported only on macOS")
        template = Path(binary).parent / "packaging" / "launchd" / AI_MEMORY_LAUNCH_AGENT
        try:
            template_text = template.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            return OperationResult("ai-memory:service", False, f"cannot read launchd template: {error}")
        if "__AI_MEMORY_BIN__" not in template_text or "__HOME__" not in template_text:
            return OperationResult("ai-memory:service", False, "launchd template has required placeholders missing")
        launch_agents = context.home / "Library" / "LaunchAgents"
        logs = context.home / "Library" / "Logs" / "ai-memory"
        plist = launch_agents / AI_MEMORY_LAUNCH_AGENT
        try:
            launch_agents.mkdir(parents=True, exist_ok=True)
            logs.mkdir(parents=True, exist_ok=True)
            plist.write_text(
                template_text.replace("__AI_MEMORY_BIN__", binary).replace("__HOME__", str(context.home)),
                encoding="utf-8",
            )
        except OSError as error:
            return OperationResult("ai-memory:service", False, str(error))
        launchctl = context.executable_finder("launchctl") or "launchctl"
        domain = f"gui/{os.getuid()}"
        registered = context.runner.run((launchctl, "print", f"{domain}/{AI_MEMORY_LABEL}"))
        if registered.error or registered.timed_out:
            return OperationResult("ai-memory:service", False, command_failure(registered))
        if registered.succeeded:
            removed = context.runner.run((launchctl, "bootout", f"{domain}/{AI_MEMORY_LABEL}"))
            if not removed.succeeded:
                return OperationResult("ai-memory:service", False, command_failure(removed))
        loaded = context.runner.run((launchctl, "bootstrap", domain, str(plist)))
        if not loaded.succeeded:
            return OperationResult("ai-memory:service", False, command_failure(loaded))
        return OperationResult("ai-memory:service", True, "LaunchAgent configured")

    def _configure_detected_integrations(self, context: EnvironmentContext, binary: str) -> tuple[OperationResult, ...]:
        operations: list[OperationResult] = []
        for harness in self.harnesses:
            if harness not in {"codex", "opencode", "copilot"}:
                continue
            if context.executable_finder(harness):
                operations.append(self._configure_integration(context, binary, harness, "mcp"))
                if harness != "copilot":
                    operations.append(self._configure_integration(context, binary, harness, "hooks"))
        return tuple(operations)

    def _configure_integration(
        self,
        context: EnvironmentContext,
        binary: str,
        harness: str,
        capability: str,
    ) -> OperationResult:
        if harness not in {"codex", "opencode", "copilot"}:
            return OperationResult(f"ai-memory:{harness}-{capability}", False, "unsupported harness")
        if harness == "copilot" and capability == "hooks":
            return OperationResult("ai-memory:copilot-hooks", True, "not supported by Copilot")
        if capability == "mcp":
            client = "vscode-copilot" if harness == "copilot" else harness
            argv: tuple[str, ...] = (binary, "install-mcp", "--client", client, "--apply")
            if harness == "copilot":
                argv = (*argv, "--config-file", str(context.root / ".vscode" / "mcp.json"))
        else:
            argv = (binary, "install-hooks", "--agent", harness, "--apply")
        result = context.runner.run(argv, timeout=60)
        action_id = f"ai-memory:{harness}-{capability}"
        if not result.succeeded:
            return OperationResult(action_id, False, command_failure(result))
        verified = self._harness_checks(context, harness)
        wanted = next((check for check in verified if check.id == f"{harness}-{capability}"), None)
        if wanted is None or wanted.status != RequirementStatus.OK:
            return OperationResult(action_id, False, "installer completed but integration verification failed")
        return OperationResult(action_id, True, "configured")


def architecture_artifact(architecture: str) -> str | None:
    """Translate macOS architecture facts to the official release suffix."""
    normalized = architecture.lower()
    if normalized in {"arm64", "aarch64"}:
        return "aarch64"
    if normalized == "x86_64":
        return "x86_64"
    return None


def command_failure(result: CommandResult) -> str:
    """Summarize failures without copying arbitrary command output into reports."""
    if result.timed_out:
        return result.error or "timed out"
    if result.error:
        return result.error
    return f"command exited {result.returncode}"


def extracted_ai_memory_distribution(extracted: Path) -> tuple[Path | None, Path | None]:
    """Locate only a release layout containing both the executable and template."""
    for template in extracted.rglob(AI_MEMORY_LAUNCH_AGENT):
        if template.parent.name != "launchd" or template.parent.parent.name != "packaging":
            continue
        distribution = template.parent.parent.parent
        binary = distribution / "ai-memory"
        if binary.is_file():
            return binary, distribution
    return None, None


class GlobalSkillRequirement(EnvironmentRequirement):
    """Shared read-only discovery and authorized install flow for a global skill."""

    skill_name: str
    install_command: tuple[str, ...]
    cli_listing_command: tuple[str, ...] | None = None
    requires_verified_origin = False

    def __init__(self, harnesses: Sequence[str]) -> None:
        self.harnesses = tuple(harnesses)

    def diagnose(self, context: EnvironmentContext, platform: PlatformInfo) -> RequirementResult:
        npx = context.executable_finder("npx")
        tooling = (
            ("node", "Node.js", platform.node_version),
            ("npm", "npm", platform.npm_version),
            ("npx", "npx", platform.npx_version),
        )
        checks: list[CheckResult] = [CheckResult(
            identifier,
            label,
            RequirementStatus.OK if version else RequirementStatus.MISSING,
            version or "not found in PATH",
        ) for identifier, label, version in tooling]
        cli_installed = False
        if npx and self.cli_listing_command:
            listing = context.runner.run((npx, *self.cli_listing_command))
            cli_installed = listing.succeeded and skill_name_in_output(listing.stdout, self.skill_name)
            checks.append(CheckResult(
                "official-cli",
                "official CLI",
                RequirementStatus.OK if cli_installed else RequirementStatus.MISSING,
                "listed globally" if cli_installed else "not listed or CLI unavailable",
                required=False,
            ))
        path, origin_verified = self._installed_path(context)
        if cli_installed or (path is not None and (origin_verified or not self.requires_verified_origin)):
            installed_status = RequirementStatus.OK
            installed_detail = str(path) if path is not None else "listed by official CLI"
        elif path is not None:
            installed_status = RequirementStatus.PARTIAL
            installed_detail = "skill directory found but origin is not verified"
        else:
            installed_status = RequirementStatus.MISSING
            installed_detail = "not installed globally"
        checks.append(CheckResult("global", "global skill", installed_status, installed_detail))
        if installed_status == RequirementStatus.OK:
            checks.extend(self._link_checks(context))
        actions: tuple[RepairAction, ...] = ()
        tooling_ready = all(version for _identifier, _label, version in tooling)
        if npx and tooling_ready and any(check.status != RequirementStatus.OK for check in checks if check.required):
            actions = (RepairAction(
                f"{self.id}:install",
                self.install_description(),
                self.id,
                ("npx " + " ".join(self.install_command),),
            ),)
        overall_status = installed_status if installed_status != RequirementStatus.OK else requirement_status(checks)
        return RequirementResult(
            id=self.id,
            name=self.name,
            description=self.description,
            required=True,
            status=overall_status,
            checks=tuple(checks),
            actions=actions,
        )

    def repair(
        self,
        context: EnvironmentContext,
        platform: PlatformInfo,
        action_ids: set[str],
    ) -> tuple[OperationResult, ...]:
        action_id = f"{self.id}:install"
        if action_id not in action_ids:
            return ()
        npx = context.executable_finder("npx")
        if not npx:
            return (OperationResult(action_id, False, "npx unavailable"),)
        result = context.runner.run((npx, *self.install_command), timeout=120)
        if not result.succeeded:
            return (OperationResult(action_id, False, command_failure(result)),)
        verified = self.diagnose(context, platform)
        if verified.status != RequirementStatus.OK:
            return (OperationResult(action_id, False, "installer completed but skill verification failed"),)
        return (OperationResult(action_id, True, "installed and verified"),)

    def _installed_path(self, context: EnvironmentContext) -> tuple[Path | None, bool]:
        for root in self._skill_roots(context):
            directory = root / self.skill_name
            skill = directory / "SKILL.md"
            if safe_file_contains(skill, f"name: {self.skill_name}"):
                return directory, self._origin_verified(directory)
        return None, False

    def _origin_verified(self, directory: Path) -> bool:
        return True

    def _skill_roots(self, context: EnvironmentContext) -> tuple[Path, ...]:
        return (
            context.home / ".agents" / "skills",
            context.home / ".codex" / "skills",
            context.home / ".config" / "opencode" / "skills",
        )

    def _link_checks(self, context: EnvironmentContext) -> tuple[CheckResult, ...]:
        checks: list[CheckResult] = []
        for harness in self.harnesses:
            if harness not in {"codex", "opencode"} or not context.executable_finder(harness):
                continue
            linked = self._known_harness_link(context, harness)
            checks.append(CheckResult(
                f"{harness}-link",
                f"{harness.title()} skill link",
                RequirementStatus.OK if linked else RequirementStatus.MISSING,
                "linked" if linked else "not linked",
            ))
        return tuple(checks)

    def _known_harness_link(self, context: EnvironmentContext, harness: str) -> bool:
        roots = {
            "codex": (
                context.home / ".codex" / "skills",
                context.home / ".agents" / "skills",
            ),
            "opencode": (
                context.home / ".agents" / "skills",
                context.home / ".config" / "opencode" / "skills",
            ),
        }[harness]
        return any(safe_file_contains(root / self.skill_name / "SKILL.md", f"name: {self.skill_name}") for root in roots)

    def install_description(self) -> str:
        return f"Install {self.name} globally using its official npx command"


class CavemanRequirement(GlobalSkillRequirement):
    id = "caveman"
    name = "caveman"
    description = "Compact engineering communication skill"
    skill_name = "caveman"
    install_command = ("skills", "add", "JuliusBrussee/caveman", "-g")
    cli_listing_command = ("--no-install", "skills", "ls", "-g")
    requires_verified_origin = True

    def _origin_verified(self, directory: Path) -> bool:
        return safe_file_contains(directory / ".skill-meta.json", "JuliusBrussee/caveman")


class TlcSpecDrivenRequirement(GlobalSkillRequirement):
    id = "tlc-spec-driven"
    name = "tlc-spec-driven"
    description = "Tech Leads Club spec-driven workflow skill"
    skill_name = "tlc-spec-driven"
    install_command = ("@tech-leads-club/agent-skills", "install", "-s", "tlc-spec-driven", "-g")
    requires_verified_origin = True

    def _origin_verified(self, directory: Path) -> bool:
        return safe_file_contains(directory / ".skill-meta.json", "tech-leads-club/agent-skills")


def skill_name_in_output(output: str, name: str) -> bool:
    """Match the exact skill identifier, not a similarly named package."""
    return any(line.strip().split(maxsplit=1)[0] == name for line in output.splitlines() if line.strip())
