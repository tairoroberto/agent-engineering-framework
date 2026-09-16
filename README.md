# Agent Engineering Framework

Local-first, language-neutral engineering behavior for AI agents. It keeps one versioned framework, thin harness adapters, technology profiles, and local project rules separate.

## Layers and authority

`Framework -> technology profile -> project rules` is loading order. Authority: `framework invariants -> project AGENTS.md -> current source -> ai-memory history`. Memory is historical evidence, never a rules engine.

Framework owns how agents cooperate. A project owns architecture, commands, release policy, domain rules, and AGENTS.md outside managed block.

## Install

```bash
/path/to/agent-engineering-framework/bin/agent-kit init --profile flutter
/path/to/agent-engineering-framework/bin/agent-kit init --force --yes
/path/to/agent-engineering-framework/bin/agent-kit install
/path/to/agent-engineering-framework/bin/agent-kit doctor
/path/to/agent-engineering-framework/bin/agent-kit sync
/path/to/agent-engineering-framework/bin/agent-kit env --check
```

`init` creates `.agent-framework.toml`, copies lazy-load assets to `.agent-managed/agent-engineering-framework/`, backs up AGENTS.md once, and adds only its marker block. When ai-memory is enabled it creates `.ai-memory.toml` only when absent; that file becomes project-owned immediately and is thereafter preserved byte for byte. `sync` uses the same idempotent bootstrap.

In an interactive `init`, the CLI also offers `Adicionar agent-kit ao PATH ...? [y/N]` when its managed entry is absent. Zsh targets `~/.zshrc` and Bash targets `~/.bash_profile`. The default is no, the entry is idempotent, and non-interactive initialization never changes the shell profile, including with `--yes`.

`init --force` repairs a partial or corrupted managed installation. It reuses a valid manifest unless explicit profile/harness flags override it, stages and validates model selection before project writes, creates `.agent-managed/backups/reinstall-<id>/`, removes only obsolete ownership-ledger files, runs `doctor`, and rolls the inventoried paths back on failure. Non-interactive use requires `--yes`; `--reuse-model-lock` keeps a valid lock. It never recursively deletes harness directories or touches `.specs`, source, evidence, project extensions, or existing ai-memory configuration.

`sync` also installs discoverable adapters for OpenCode (`.opencode`), Codex (`.codex`), GitHub Copilot (`.github/agents`, instructions and prompts), and Claude Code (`.claude/agents` and commands). These define roles, bounded capabilities, compact-context loading, and harness-local model mechanics. Existing files are backed up on adoption. Later manual edits to a managed adapter are diagnosed instead of silently overwritten. A project with audited harness-specific state/gate adapters may declare `[harness] managed_adapters = false` and keep that override local.
If a framework-owned adapter must be restored, `agent-kit sync --replace-managed` first creates a timestamp-free managed backup and then restores only that managed file; it never alters project rules or source.

`install` registers the framework home in user configuration, never in a consumer repository. `status` reports selected profile/protocol/registry. `diff` is read-only and reports whether managed assets or routing block would change. `env --check` is also read-only: it diagnoses Node.js/npm/npx, ai-memory, Caveman, TLC Spec-Driven, and available harness integrations. Plain `env` previews only known repairs and asks for approval; `env --yes` applies that preview non-interactively. `env --json` emits a structured read-only report and cannot be combined with `--yes`. Managed project-local assets are intentional: current Codex/OpenCode discovery differs, while one agent-kit-generated copy gives both harnesses the same protocol without hard-coded consumer paths or manual copies.

For formal feature tasks, the shared router derives a portable capability class
from declared metadata, valid persisted classification, or deterministic
inference. Low-confidence inference blocks instead of silently defaulting to a
strong model. Each generated harness `routing.json` resolves the floor to local
agents/models, while `.agent-managed/model-catalog.lock.json` records discovered
availability and capabilities without placing vendor IDs in shared policy.
Reviewer and QA use the same provider-aware resolution, rather than fixed
free-model profiles. Quota, rate-limit, and unavailable-model failures are
terminal for that child; the orchestrator uses only fallbacks already approved
in the activity plan. A named provider remains strict; `auto` may use an
approved provider fallback. If the
active harness cannot cancel a pending child, dependent work stops and the
operator cancels it in the harness UI.

Before `continue`, `feature`, or `review` dispatches agents, `agent-kit` creates
a hash-bound model proposal for Orchestrator, Developer, Reviewer, and
risk/task-required QA. The
user approves it or supplies per-role model overrides; these choices never leak
to another activity. Non-interactive execution requires explicit `--approve`
or `--yes`. Every role receives a compact `ContextCapsule`, and execution is
recorded as a fact-only `DispatchReceipt` with model, effort, token/cache/cost,
result, and gates—never prompts, transcripts, sessions, or reasoning.

Use `agent-kit tasks list` to show open tasks from every canonical feature state.
Add `--feature`, repeated `--status`, `--all`, or `--json` for focused and
machine-readable views.

## Ownership

Framework: `.agent-managed/agent-engineering-framework/**`, content between `agent-framework` markers in AGENTS.md, model lock/runtime contracts, ledger-listed generated harness profiles/configuration, and framework workflow adapters. Project: AGENTS.md outside markers, manifest values, existing `.ai-memory.toml`, `.specs`, source, architecture, tests, domain rules, state providers, workflow hooks, and non-ledger harness extensions.

## Harnesses, profiles, memory

Codex, OpenCode, Copilot, and Claude Code load the same managed core; adapters define discovery/capability only. `generic`, `flutter`, `laravel`, and `kotlin-multiplatform` contain reusable discovery/validation guidance only. Use ai-memory through targeted retrieval; current source and project rules win contradictions.

`skills/engineering-protocol` is the single shared protocol activation point. It composes canonical `core/` policy rather than duplicating it. Technology profiles and project extensions supply only their own layer.

## Portable state and cross-harness continuation

The framework default stores compact, harness-neutral work state in
`.specs/features/<feature>/state.json`. The managed `state/` assets provide a
schema plus `state.py` and `validate_state.py`. Use `state.py new <feature>`,
`validate <feature>`, `get <feature> --json`, `mark`, `gate`, and `handoff`.
OpenCode and Codex read the same file, reconcile it with Git/source/project
rules, then resume. `lastHarness` is diagnostic only. State must never contain
sessions, transcripts, chain-of-thought, credentials, or secrets.

## Execution convergence

Developer Closure proves technical readiness, not review approval. The
Developer runs project-selected format, analysis/lint, and focused tests for
the task scope, then records compact evidence before review. Reviewer remains
read-only and returns one `BLOCKER`/`MAJOR`/`MINOR` batch. QA remains
non-mutating and is dispatched only when risk, task gates, project policy, or
acceptance requires it.

Gate evidence is hash-bound to the task boundary, current source, class, and
command. An identical PASS can be reused; an identical FAIL is not retried
automatically. Review/fix, repeat-failure, and no-progress budgets live in the
portable execution policy. Exhaustion becomes `blocked` plus
`human_escalation`, never an endless loop. Provider quota and external/tool
failures stay separate from this budget.

A project with an audited richer state implementation may declare
`[state] provider = "project"` plus its command in `.agent-framework.toml`.
That implementation must keep the same authority boundary: project-local
evidence/handoff, no harness-owned continuation state.

## Daily operation

For a simple task, load project rules, relevant profile, and source; remain single-agent. For uncertain or broad work, the orchestrator may dispatch Explorer, Implementer, Reviewer, and Verifier with bounded ownership. Handoffs use `GOAL/STATE/FILES/DECISIONS/VERIFY/RISKS/OPEN`; no transcript or chain-of-thought transfer.

## Shared workflows and commands

The canonical workflows are `continue`, `feature`, and `review` under `workflows/`. They compose the engineering protocol; they do not duplicate its orchestration, Caveman, memory, review, or verification policy. `agent-kit sync` exposes them as OpenCode `/continue`, `/feature`, and `/review` adapters. `agent-kit install` exposes equivalent Codex global prompts as `/prompts:continue`, `/prompts:feature`, and `/prompts:review`; Codex custom prompts are global by product design, so no absolute framework path is written to consumers. Restart or open a new Codex session after installing prompts.

Projects can add verification commands or workflow defaults through their rules/profile layer. A narrowly scoped, reviewed post-workflow hook may be declared in `[workflows.<name>]` in the project manifest when a project state owner must perform a final action; it may add project closure behavior but cannot remove framework verification/review requirements. Projects must not fork a workflow to do so. `agent-kit doctor` reports missing workflows, stale OpenCode adapters, and unavailable Codex prompts; `agent-kit diff` previews OpenCode adapter changes.

See [command workflow migration](docs/command-workflow-migration.md) for the Farm reference audit, ownership map, and semantic parity matrix.
See [installation and model routing](docs/model-routing-and-installation.md) for reinstall, ai-memory, proposal/approval, receipt, and four-harness operation.
See [guia de uso em português](docs/guia-de-uso.md) for step-by-step new-project setup, sync/force recovery, open-task listing, continuation, providers, and model selection.

## Add a profile or harness

Add `profiles/<name>.md` only for reusable technology discovery and validation. Add `harness/<name>.md` only for configuration discovery, tools, capability, and model-selection mechanics. Update `agent-kit` validation and tests. Product, company, language-specific architecture, and release rules do not belong in the core.

## Troubleshooting

Run `agent-kit doctor` for project installation integrity. Run `agent-kit env --check` for local prerequisites; it exits 0 only when required dependencies are ready and 1 when attention is required. It never installs Node.js. ai-memory automatic repair is available only on macOS and uses its fixed official release route after explicit approval; other platforms remain detection-only. Copilot receives ai-memory MCP configuration only, not lifecycle hooks. `agent-kit sync` repairs only framework-owned managed assets and its marker block.

## Upgrades and teams

Commit consumer-managed files in project. A teammate clones project plus a compatible framework release, then runs `agent-kit doctor`. Projects declare `framework_version = "1"`; incompatible majors fail doctor. Future packaging can retain this contract.
