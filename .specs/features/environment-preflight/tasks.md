# Agent Kit Environment Preflight Tasks

**Design**: `.specs/features/environment-preflight/design.md`
**Status**: In Progress

## Test Coverage Matrix

> Generated from the existing stdlib unittest suite, `README.md`, and `scripts/validate_framework.py`. The repository has no separate CI or formatter configuration; strong defaults apply to new runtime behavior.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Environment runtime | unit | Every result state, action decision, platform branch, and failure path tied to ENV-01 through ENV-09 | `tests/test_environment.py` | `python3 -m unittest tests/test_environment.py` |
| CLI adapter | integration | Text/JSON, approval, refusal, repeated execution, and exit-code behavior through the real CLI with fake executables | `tests/test_agent_kit.py` | `python3 -m unittest tests/test_agent_kit.py` |
| Documentation and structural registry | documentation validation | Commands and platform boundaries match parser behavior; framework structural gate passes | `README.md`, `docs/guia-de-uso.md`, `scripts/validate_framework.py` | `python3 scripts/validate_framework.py` |

## Gate Check Commands

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | Runtime or CLI task | `python3 -m unittest tests/test_environment.py tests/test_agent_kit.py` |
| Full | Last executable behavior phase | `python3 -m unittest` |
| Build | Documentation or final integration | `python3 scripts/validate_framework.py && python3 -m unittest` |

## Execution Plan

### Phase 1: Runtime foundation

```text
T1 -> T2
```

### Phase 2: Requirements and repair

```text
T3; T4
```

### Phase 3: Command and documentation

```text
T5 -> T6 -> T7
```

## Task Breakdown

### Phase 1: Runtime foundation

### T1: Add environment result and process runtime

**What**: Create the stdlib-only environment result model, bounded process runner, platform facts, report aggregation, and test fakes.
**Where**: `state/environment.py`
**Depends on**: None
**Reuses**: `state/catalog.py`, `state/activity.py`, and `tests/test_agent_kit.py` unittest conventions.
**Requirement**: ENV-01, ENV-02
**Tests**: unit
**Gate**: quick
**Status**: Complete

### T2: Diagnose ai-memory and harness capabilities

**What**: Implement binary, initialization, launchd, HTTP, CLI, and Codex/OpenCode/Copilot MCP-or-hook diagnosis with secret-safe facts.
**Where**: `state/environment.py`
**Depends on**: T1
**Reuses**: `SUPPORTED_HARNESSES`, `HARNESS_DIRS`, and `ai_memory_validation` boundaries from `bin/agent-kit`.
**Requirement**: ENV-01, ENV-03
**Tests**: unit
**Gate**: quick

### Phase 2: Requirements and repair

### T3: Add authorized macOS ai-memory repair

**What**: Implement architecture-safe official release installation, initialization, launchd rendering, idempotent service repair, and post-repair verification.
**Where**: `state/environment.py`
**Depends on**: T2
**Reuses**: Python temporary-directory and filesystem primitives already used by `bin/agent-kit`.
**Requirement**: ENV-06, ENV-07
**Tests**: unit
**Gate**: quick

### T4: Add Caveman and TLC requirements

**What**: Implement no-install official CLI discovery, conservative global-root verification, known linkage state, and authorized canonical skill installation.
**Where**: `state/environment.py`
**Depends on**: T1
**Reuses**: The managed OpenCode global skill-path convention in `bin/agent-kit`.
**Requirement**: ENV-08, ENV-09
**Tests**: unit
**Gate**: quick

### Phase 3: Command and documentation

### T5: Expose the `env` command

**What**: Add parser flags, interactive action preview, `--check`, `--yes`, `--json`, recheck, and 0/1/2 exit semantics without changing existing commands.
**Where**: `bin/agent-kit`
**Depends on**: T2, T3, T4
**Reuses**: `command_doctor`, `command_activity`, `fail()`, and existing subparser conventions.
**Requirement**: ENV-01, ENV-04, ENV-05
**Tests**: integration
**Gate**: full

### T6: Document the concise command reference

**What**: Add `env` to the primary framework command reference and structural registry.
**Where**: `README.md`
**Depends on**: T5
**Reuses**: Existing installation and troubleshooting sections.
**Requirement**: ENV-04
**Tests**: documentation validation
**Gate**: build

### T7: Document Portuguese diagnosis and repair workflows

**What**: Add runnable `env`, `--check`, `--yes`, and macOS/Copilot limitation examples to the usage guide.
**Where**: `docs/guia-de-uso.md`
**Depends on**: T6
**Reuses**: Existing scenario-oriented Portuguese command sequences.
**Requirement**: ENV-04, ENV-05, ENV-06, ENV-08
**Tests**: documentation validation
**Gate**: build

## Phase Execution Map

```text
Phase 1: T1 -> T2
Phase 2: T3; T4
Phase 3: T5 -> T6 -> T7
```

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1 | Runtime boundary | ✅ Granular |
| T2 | ai-memory diagnosis | ✅ Granular |
| T3 | ai-memory repair | ✅ Granular |
| T4 | Skill requirements | ✅ Granular |
| T5 | CLI adapter | ✅ Granular |
| T6 | Primary reference | ✅ Granular |
| T7 | Portuguese guide | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | None | ✅ Match |
| T2 | T1 | T1 -> T2 | ✅ Match |
| T3 | T2 | Cross-phase predecessor | ✅ Match |
| T4 | T1 | Cross-phase predecessor | ✅ Match |
| T5 | T2, T3, T4 | Cross-phase predecessors | ✅ Match |
| T6 | T5 | T5 -> T6 | ✅ Match |
| T7 | T6 | T6 -> T7 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | Environment runtime | unit | unit | ✅ OK |
| T2 | Environment runtime | unit | unit | ✅ OK |
| T3 | Environment runtime | unit | unit | ✅ OK |
| T4 | Environment runtime | unit | unit | ✅ OK |
| T5 | CLI adapter | integration | integration | ✅ OK |
| T6 | Documentation | documentation validation | documentation validation | ✅ OK |
| T7 | Documentation | documentation validation | documentation validation | ✅ OK |
