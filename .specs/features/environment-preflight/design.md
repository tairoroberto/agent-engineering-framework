# Agent Kit Environment Preflight Design

**Spec**: `.specs/features/environment-preflight/spec.md`
**Status**: Approved by the supplied implementation request

## Architecture Overview

`bin/agent-kit` remains the only command entry point. A new stdlib-only `state/environment.py` follows the existing `state/catalog.py` and `state/activity.py` arrangement: it owns domain results and process orchestration, while the CLI parses flags, presents text/JSON, asks once for consent, and translates the aggregate result to the established exit-code convention.

```text
agent-kit env
  -> EnvironmentService.inspect()
     -> PlatformProbe
     -> AiMemoryRequirement
     -> CavemanRequirement
     -> TlcSpecDrivenRequirement
     -> HarnessIntegrationProbe
  -> text or JSON report
  -> explicit consent
  -> EnvironmentService.remediate(actions)
  -> fresh inspect()
```

## Code Reuse Analysis

### Existing Components to Leverage

| Component | Location | How to Use |
| --- | --- | --- |
| CLI parser and handlers | `bin/agent-kit` | Add one subparser and one handler following `doctor`, `tasks`, and activity JSON patterns. |
| CLI error convention | `bin/agent-kit:450` | Preserve `fail()` for code 2 and let an unhealthy diagnosis return code 1. |
| Harness constants and paths | `bin/agent-kit:46-54` | Move no existing ownership; pass the existing supported harness list into the service. |
| Harness executable detection | `bin/agent-kit:1419-1422` | Reuse `shutil.which` semantics through an injectable probe. |
| ai-memory project marker validation | `bin/agent-kit:653-706` | Keep it project-scoped and separate from user-machine ai-memory health. |
| CLI test style | `tests/test_agent_kit.py` | Use temporary roots and homes; add a focused runtime test module with faked process outcomes. |

### Integration Points

| System | Integration Method |
| --- | --- |
| ai-memory native binary | Read-only `--version`, `status`, installer help-derived `install-mcp`/`install-hooks`, and authorized `init`. |
| macOS launchd | `launchctl print`, then authorized `bootout`/`bootstrap` only for repair. |
| HTTP health | Local `curl` status-code probe; 200, 401, and 405 are responses, with 405 explicitly healthy for `/mcp`. |
| Caveman | Official `npx skills` command and conservative known-root verification. |
| TLC | Official `@tech-leads-club/agent-skills` command and origin-aware known-root verification. |
| Harnesses | Existing executable detection plus official ai-memory-generated config/plugin locations. |

## Components

### ProcessRunner

- **Purpose**: Execute bounded external commands and return an immutable result without raising process errors into independent checks.
- **Location**: `state/environment.py`
- **Interfaces**:
  - `run(argv, timeout=...) -> CommandResult`
- **Dependencies**: Python standard library `subprocess`.
- **Reuses**: The repository's existing subprocess behavior and timeout discipline.

### EnvironmentRequirement

- **Purpose**: Provide stable identifiers, human descriptions, diagnostics, action plans, repair, and verification.
- **Location**: `state/environment.py`
- **Interfaces**:
  - `diagnose(context) -> RequirementResult`
  - `actions(result) -> list[RepairAction]`
  - `repair(context, action) -> list[OperationResult]`
- **Dependencies**: `ProcessRunner`, filesystem probe, platform probe.
- **Reuses**: None; this is the smallest new seam needed because no environment abstraction exists.

### AiMemoryRequirement

- **Purpose**: Distinguish binary, data initialization, launchd, HTTP, CLI, and per-harness integration states.
- **Location**: `state/environment.py`
- **Interfaces**: Implements `EnvironmentRequirement`.
- **Dependencies**: Canonical application location, `launchctl`, `curl`, and the installed ai-memory CLI.
- **Reuses**: Existing project marker validator only as a separate optional project detail.

### SkillRequirements

- **Purpose**: Diagnose and repair Caveman and tlc-spec-driven with their official package identifiers.
- **Location**: `state/environment.py`
- **Interfaces**: `CavemanRequirement` and `TlcSpecDrivenRequirement` implement `EnvironmentRequirement`.
- **Dependencies**: Node/npm/npx platform facts and known skill-root probe.
- **Reuses**: Existing OpenCode managed configuration's declared global skill locations as discovery evidence, not as an installer.

### EnvironmentService and Report Renderer

- **Purpose**: Aggregate independent requirement results, continue after partial failures, construct a known action plan, serialize JSON, and render compact human output.
- **Location**: `state/environment.py`
- **Interfaces**:
  - `inspect() -> EnvironmentReport`
  - `repair(actions) -> list[OperationResult]`
  - `report_to_json(report) -> dict`
  - `render_report(report) -> str`
- **Dependencies**: Requirement collection and context.
- **Reuses**: Existing JSON output convention in `bin/agent-kit`.

## Data Models

### RequirementStatus

```python
class RequirementStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    NOT_RUNNING = "not_running"
    MISCONFIGURED = "misconfigured"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
```

### RequirementResult

```python
@dataclass(frozen=True)
class RequirementResult:
    id: str
    name: str
    description: str
    required: bool
    status: RequirementStatus
    version: str | None
    checks: tuple[CheckResult, ...]
    actions: tuple[RepairAction, ...]
```

`healthy` is calculated from required result statuses. Unsupported optional capabilities, such as Copilot hooks, do not make a requirement unhealthy.

## Error Handling Strategy

| Error Scenario | Handling | User Impact |
| --- | --- | --- |
| Binary missing | `MISSING` with a known install action if supported | User can approve only that action. |
| Binary command fails or times out | `ERROR` check, remaining requirements continue | Full report still identifies unrelated healthy dependencies. |
| HTTP endpoint returns 405 | `OK` server-response check | No false service failure. |
| launchd registered but not running | `NOT_RUNNING` and repair action | A repair re-renders and reboots the owned agent only after consent. |
| Non-macOS ai-memory install needed | `UNSUPPORTED` action note, no installer | User receives a clear manual limitation. |
| One repair fails | Operation failure retained, independent actions continue, final check governs exit 1 | No hidden partial success. |

## Risks & Concerns

| Concern | Location | Impact | Mitigation |
| --- | --- | --- | --- |
| `agent-kit` is a large single CLI module | `bin/agent-kit` | New process logic could make command parsing harder to test. | Keep all diagnostic and repair logic in `state/environment.py`; CLI only adapts flags and output. |
| ai-memory CLI evolves | Official CLI installer flags | Hardcoded stale agent names could damage config. | Inspect the installed CLI help before applying; invoke only fixed supported identifiers and verify output files afterward. |
| Global skill CLIs may download themselves | `npx` | A diagnostic could mutate the machine before consent. | Diagnose with no-install invocation and known-root fallback; use networked install only after explicit authorization. |
| Copilot MCP is workspace-scoped | VS Code configuration | A global command could write an unintended project file. | Use the current explicit `--root` target and name the file in the action preview. |
| User secrets in existing generated plugins | ai-memory hook integrations | Diagnostics must not expose auth tokens. | Report only boolean/path capability facts; never echo config bodies, command output containing credentials, or environment variables. |

## Tech Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Runtime placement | New `state/environment.py` | Matches the existing portable Python runtime modules without adding a second CLI. |
| Process seams | Injectable runner and filesystem/platform probes | Lets tests simulate all installers and service states without global mutations. |
| Official commands | ai-memory native CLI, `npx skills`, and official TLC npx package | Agent Kit orchestrates external ownership rather than reproducing vendor configuration logic. |
| Mac release selection | Fixed GitHub release URL with architecture whitelist | Prevents arbitrary URL execution and avoids assuming Apple Silicon. |
| PATH link | Not automated | The canonical ai-memory location remains functional without sudo. |
