# Agent Kit Environment Preflight Specification

## Problem Statement

The framework currently validates a consumer project's managed assets, but it cannot prove that the local machine can run the multi-harness workflow. Users discover a stopped ai-memory service, missing global skills, or an unavailable Node runtime only when an agent workflow fails.

## Goals

- [ ] Provide one safe command that reports the machine, runtime dependencies, and supported harness integrations.
- [ ] Repair only known, user-approved requirements and recheck the resulting environment.
- [ ] Keep diagnosis usable in CI and scripts without modifying the machine.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Linux or Windows ai-memory installer | The first release supports automatic ai-memory installation only on macOS. |
| Node.js installation | Node package managers and privileged installation policies are outside agent-kit ownership. |
| ai-memory symlink in `/usr/local/bin` | A functional canonical binary does not require sudo or a PATH mutation. |
| Lifecycle hooks for VS Code Copilot | ai-memory documents Copilot as MCP-only. |
| Installing arbitrary dependency URLs | Only fixed official project commands and release URLs are allowed. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- |
| Default environment scope | The current `--root` is used only for the workspace-scoped Copilot MCP file; other checks are user-local. | Existing CLI already owns `--root`, while the official Copilot integration is workspace-scoped. | yes |
| Interactive approval | Plain `env` asks once only when repairable actions exist and stdin is a TTY. | This preserves the existing explicit-consent convention. | yes |
| Noninteractive behavior | `--check` and `--json` never prompt or write; noninteractive plain `env` reports unresolved requirements. | CI must be deterministic and must not alter a developer environment. | yes |
| Skill discovery | The official CLI is queried without allowing `npx` to download a tool during diagnosis, then known skill roots provide a conservative fallback. | A diagnostic must not create an implicit global installation. | yes |
| Open questions | all resolved or logged above | The supplied command, platform, and installation requirements are sufficient for this first release. | yes |

**Open questions: none.**

## User Stories

### P1: Diagnose a local environment

**User Story**: As a framework user, I want `agent-kit env` to show whether my machine can run ai-memory, Caveman, TLC, and supported harnesses so that I can fix a problem before a workflow starts.

**Why P1**: A reliable diagnosis is the prerequisite for every repair flow.

**Acceptance Criteria**:

1. WHEN the user runs `agent-kit env` THEN the system SHALL report OS, architecture, Node.js, npm, npx, ai-memory, Caveman, tlc-spec-driven, and detected supported harnesses.
2. WHEN a requirement has multiple subchecks THEN the system SHALL expose `OK`, `MISSING`, `NOT_RUNNING`, `MISCONFIGURED`, `PARTIAL`, `UNSUPPORTED`, or `ERROR` rather than reducing the result to an installed boolean.
3. WHEN ai-memory is discoverable through PATH or `~/Applications/ai-memory/ai-memory` THEN the system SHALL report its canonical binary path and version without requiring a PATH symlink.
4. WHEN ai-memory is installed THEN the system SHALL separately check initialization, launchd registration and running state on macOS, HTTP response on `127.0.0.1:49374/mcp`, CLI status, and the installed Codex, OpenCode, and Copilot integrations.
5. WHEN the HTTP endpoint returns `405` THEN the system SHALL classify the HTTP service check as healthy because the endpoint responded.
6. WHEN a detected harness does not support lifecycle hooks THEN the system SHALL report that capability as unsupported without making the environment unhealthy solely for that reason.

**Independent Test**: Run the command against faked healthy, missing, partial, and unsupported environments and inspect both text and JSON reports.

### P1: Repair known requirements with explicit consent

**User Story**: As a framework user, I want the command to explain and ask before making local changes so that repair remains predictable and safe.

**Why P1**: Environment configuration changes user-level services and global skills.

**Acceptance Criteria**:

1. WHEN repairable problems are found in an interactive session THEN the system SHALL print the exact known changes and ask for consent before executing any install or repair command.
2. WHEN the user declines repair, uses `--check`, or uses `--json` THEN the system SHALL not write files, invoke an installer, register a service, or install a global skill.
3. WHEN the user passes `--yes` THEN the system SHALL run only the already classified official repair actions and SHALL recheck every requirement after those actions finish.
4. IF one repair action fails THEN the system SHALL continue independent repair actions, report the individual failure, and return an unresolved result after the final recheck.
5. WHEN all requirements are healthy THEN the system SHALL exit with code 0; WHEN a requirement remains unresolved THEN the system SHALL exit with code 1; IF the CLI has an invalid invocation or internal command failure THEN the system SHALL exit with code 2.
6. WHEN the command is run repeatedly against a healthy environment THEN the system SHALL not reinstall skills, duplicate harness configuration, or re-bootstrap an already valid LaunchAgent.

**Independent Test**: Exercise accept, decline, partial failure, repeat, check-only, JSON, and exit-code scenarios with fake commands and a temporary home directory.

### P1: Install and repair ai-memory on macOS

**User Story**: As a macOS user with a missing or broken ai-memory setup, I want a safe repair path so that lifecycle memory works without manual service surgery.

**Why P1**: ai-memory is required for cross-harness memory behavior.

**Acceptance Criteria**:

1. WHEN an authorized macOS installation is required THEN the system SHALL map `arm64` or `aarch64` to the `aarch64` release artifact and `x86_64` to the `x86_64` release artifact.
2. WHEN an authorized macOS installation is required THEN the system SHALL download only the fixed official ai-memory release URL, extract it into the canonical user application directory, and run `ai-memory init` before service-dependent checks.
3. WHEN ai-memory must be repaired on macOS THEN the system SHALL render the packaged launchd template with the selected binary and home paths, create needed log and LaunchAgents directories, and use `launchctl print` before `bootout` or `bootstrap`.
4. WHEN a valid ai-memory LaunchAgent is already registered and healthy THEN the system SHALL leave it unchanged; WHEN its configuration requires repair THEN the system SHALL boot it out before a single bootstrap.
5. WHERE the host is not macOS THEN the system SHALL detect an existing ai-memory installation when possible and SHALL report automatic ai-memory installation as unsupported.

**Independent Test**: Assert architecture selection, missing/stopped/running service states, HTTP health, idempotent reconfiguration, and unsupported platforms using a fake process runner.

### P1: Install framework skills and harness integrations

**User Story**: As a framework user, I want Caveman and TLC checked from their official distributions and ai-memory wired to supported harness capabilities so that all shared workflow behaviors are available.

**Why P1**: The framework's compact handoffs and spec-driven workflow depend on these capabilities.

**Acceptance Criteria**:

1. WHEN Caveman is missing and installation is authorized THEN the system SHALL invoke `npx skills add JuliusBrussee/caveman -g` and verify the installed result without treating a similarly named unverified folder as success.
2. WHEN tlc-spec-driven is missing and installation is authorized THEN the system SHALL invoke `npx @tech-leads-club/agent-skills install -s tlc-spec-driven -g` and verify the installed result.
3. WHEN Node.js, npm, or npx is unavailable THEN the system SHALL report that skill installation is unavailable and SHALL not attempt to install Node.js.
4. WHEN Codex or OpenCode is detected and ai-memory is repairable THEN the system SHALL use the installed ai-memory CLI's supported MCP and hook installers and verify both generated integrations after applying them.
5. WHEN VS Code Copilot is detected and ai-memory MCP is missing THEN the system SHALL use the installed ai-memory CLI's MCP installer for the target workspace and SHALL report hooks as unsupported.
6. WHEN a skill is globally installed but a supported harness linkage is known to be absent THEN the system SHALL report `PARTIAL` and offer the safe canonical skill repair action.

**Independent Test**: Verify installed, missing, installation-success, installation-failure, and known-unlinked cases without accessing real global tool state.

## Edge Cases

- IF an external executable times out or cannot be started THEN the system SHALL record an `ERROR` subcheck and continue independent checks.
- IF an ai-memory release archive lacks its expected binary or launchd template THEN the system SHALL stop that requirement's repair before replacing the canonical installation.
- IF an unsupported architecture is detected on macOS THEN the system SHALL report it as unsupported and SHALL not construct a download URL.
- IF the selected user declines the prompt THEN the system SHALL preserve the report and return code 1 without a recheck that changes state.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| ENV-01 | Diagnose a local environment | Implementing | Implementing |
| ENV-02 | Diagnose a local environment | Implementing | Implementing |
| ENV-03 | Diagnose a local environment | In Tasks | Pending |
| ENV-04 | Repair known requirements with explicit consent | In Tasks | Pending |
| ENV-05 | Repair known requirements with explicit consent | In Tasks | Pending |
| ENV-06 | Install and repair ai-memory on macOS | In Tasks | Pending |
| ENV-07 | Install and repair ai-memory on macOS | In Tasks | Pending |
| ENV-08 | Install framework skills and harness integrations | In Tasks | Pending |
| ENV-09 | Install framework skills and harness integrations | In Tasks | Pending |

**Coverage:** 9 total, 9 mapped to tasks, 0 unmapped.

## Success Criteria

- [ ] `agent-kit env`, `agent-kit env --check`, `agent-kit env --yes`, and `agent-kit env --json` have deterministic behavior.
- [ ] All direct process interactions are fakeable in tests, and no test installs a real dependency.
- [ ] Existing Agent Kit commands retain their current behavior.
