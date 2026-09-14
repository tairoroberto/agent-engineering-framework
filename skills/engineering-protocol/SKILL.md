---
name: engineering-protocol
description: Shared, project-agnostic engineering orchestration for Codex and OpenCode.
---

# Engineering protocol

Load only documents needed. Canonical policy lives in `../../core/`; do not copy or override it here.

1. Read project AGENTS.md and `.agent-framework.toml`.
2. Read relevant core policy: principles always; orchestration for delegation; verification for review/gates; memory for substantial/resumed work; handoff for transfer; Caveman for communication.
3. Read selected profile and project rules. Project rules choose commands, architecture, domain behavior, release policy.
4. Load `../../agents/` role guidance only for dispatched role.
5. For formal task metadata, use `../../state/routing.py`: `validate` before dispatch, `sync` to write ready/dependency state, and `resolve <tasks.md> <task> <harness> --provider <name>` to select implementation. Use `resolve-class <harness> <reviewClasses|qaClasses> <class> --provider <name>` for Reviewer/QA. `references/routing-policy.json` chooses portable classes; harness `routing.json` maps them to approved native candidates. `auto` permits any candidate in the active harness; a named provider is strict across Developer, Reviewer, and QA. Quota/rate-limit/unavailable is terminal: do not retry or await that child indefinitely. Rerun the same resolver with `--exclude-model <failed-model>` and use only its next candidate. If the harness cannot cancel a pending child, stop dependent dispatch and give the operator an explicit UI-cancel action. No candidate is a blocker; do not lower risk, gates, class, or a named provider.

Protocol owns the portable state baseline in `../../state/`: use it unless the
manifest declares a project-owned compatible state provider. State data remains
project-local at `.specs/features/<feature>/state.json`; it contains compact
evidence and handoff only, never harness sessions, transcripts, reasoning, or
credentials. Project rules own test commands, business rules, and any richer
state extension. Harness adapters explain discovery only. ai-memory is
historical context, never authority.

Before review, the Developer records closure from project-required conceptual
gates through the state runtime. A gate decision reuses only an identical PASS
for the same task boundary, source, kind, and command; it escalates an identical
FAIL instead of retrying it. Reviewer returns one `BLOCKER`/`MAJOR`/`MINOR`
batch. The state execution policy, not a harness turn limit, bounds review/fix
and no-progress loops. QA remains conditional on risk/task/project acceptance
and only runs non-mutating verification.
