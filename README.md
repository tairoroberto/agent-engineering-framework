# Agent Engineering Framework

Local-first, language-neutral engineering behavior for AI agents. It keeps one versioned framework, thin harness adapters, technology profiles, and local project rules separate.

## Layers and authority

`Framework -> technology profile -> project rules` is loading order. Authority: `framework invariants -> project AGENTS.md -> current source -> ai-memory history`. Memory is historical evidence, never a rules engine.

Framework owns how agents cooperate. A project owns architecture, commands, release policy, domain rules, and AGENTS.md outside managed block.

## Install

```bash
/path/to/agent-engineering-framework/bin/agent-kit init --profile flutter
/path/to/agent-engineering-framework/bin/agent-kit install
/path/to/agent-engineering-framework/bin/agent-kit doctor
/path/to/agent-engineering-framework/bin/agent-kit sync
```

`init` creates `.agent-framework.toml`, copies lazy-load assets to `.agent-managed/agent-engineering-framework/`, backs up AGENTS.md once, and adds only its marker block. It also backs up and replaces only the three framework-owned OpenCode workflow adapters. It never changes `.ai-memory.toml`. `sync` updates managed assets, the marker block, and those adapters deterministically.

`install` registers the framework home in user configuration, never in a consumer repository. `status` reports selected profile/protocol/registry. `diff` is read-only and reports whether managed assets or routing block would change. Managed project-local assets are intentional: current Codex/OpenCode discovery differs, while one agent-kit-generated copy gives both harnesses the same protocol without hard-coded consumer paths or manual copies.

## Ownership

Framework: `.agent-managed/agent-engineering-framework/**`, content between `agent-framework` markers in AGENTS.md, and generated OpenCode `continue`, `feature`, and `review` adapters. Project: AGENTS.md outside markers, manifest values, `.ai-memory.toml`, source, architecture, harness config, tests, domain rules, and project-only commands such as Farm `/status`.

## Harnesses, profiles, memory

Codex and OpenCode load same managed core; adapters define discovery/capability only. `generic`, `flutter`, `laravel`, and `kotlin-multiplatform` contain reusable discovery/validation guidance only. Use ai-memory through targeted retrieval; current source and project rules win contradictions.

`skills/engineering-protocol` is the single shared protocol activation point. It composes canonical `core/` policy rather than duplicating it. Technology profiles and project extensions supply only their own layer.

## Daily operation

For a simple task, load project rules, relevant profile, and source; remain single-agent. For uncertain or broad work, the orchestrator may dispatch Explorer, Implementer, Reviewer, and Verifier with bounded ownership. Handoffs use `GOAL/STATE/FILES/DECISIONS/VERIFY/RISKS/OPEN`; no transcript or chain-of-thought transfer.

## Shared workflows and commands

The canonical workflows are `continue`, `feature`, and `review` under `workflows/`. They compose the engineering protocol; they do not duplicate its orchestration, Caverman, memory, review, or verification policy. `agent-kit sync` exposes them as OpenCode `/continue`, `/feature`, and `/review` adapters. `agent-kit install` exposes equivalent Codex global prompts as `/prompts:continue`, `/prompts:feature`, and `/prompts:review`; Codex custom prompts are global by product design, so no absolute framework path is written to consumers. Restart or open a new Codex session after installing prompts.

Projects can add verification commands or workflow defaults through their rules/profile layer. A narrowly scoped, reviewed post-workflow hook may be declared in `[workflows.<name>]` in the project manifest when a project state owner must perform a final action; it may add project closure behavior but cannot remove framework verification/review requirements. Projects must not fork a workflow to do so. `agent-kit doctor` reports missing workflows, stale OpenCode adapters, and unavailable Codex prompts; `agent-kit diff` previews OpenCode adapter changes.

See [command workflow migration](docs/command-workflow-migration.md) for the Farm reference audit, ownership map, and semantic parity matrix.

## Add a profile or harness

Add `profiles/<name>.md` only for reusable technology discovery and validation. Add `harness/<name>.md` only for configuration discovery, tools, capability, and model-selection mechanics. Update `agent-kit` validation and tests. Product, company, language-specific architecture, and release rules do not belong in the core.

## Troubleshooting

Run `agent-kit doctor`. It reports incompatible majors, malformed/missing AGENTS markers, modified managed files, unavailable profile assets, absent ai-memory configuration, and whether the requested harness executable is on PATH. It never installs tools or rewrites project-owned content. `agent-kit sync` repairs only framework-owned managed assets and its marker block.

## Upgrades and teams

Commit consumer-managed files in project. A teammate clones project plus a compatible framework release, then runs `agent-kit doctor`. Projects declare `framework_version = "1"`; incompatible majors fail doctor. Future packaging can retain this contract.
