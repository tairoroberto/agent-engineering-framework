# Agent Engineering Framework

Local-first, language-neutral engineering behavior for AI agents. It keeps one versioned framework, thin harness adapters, technology profiles, and local project rules separate.

## Layers and authority

`Framework -> technology profile -> project rules` is loading order. Authority: `framework invariants -> project AGENTS.md -> current source -> ai-memory history`. Memory is historical evidence, never a rules engine.

Framework owns how agents cooperate. A project owns architecture, commands, release policy, domain rules, and AGENTS.md outside managed block.

## Install

```bash
/path/to/agent-engineering-framework/bin/agent-kit init --profile flutter
/path/to/agent-engineering-framework/bin/agent-kit doctor
/path/to/agent-engineering-framework/bin/agent-kit sync
```

`init` creates `.agent-framework.toml`, copies lazy-load assets to `.agent-managed/agent-engineering-framework/`, backs up AGENTS.md once, and adds only its marker block. It never changes `.ai-memory.toml`. `sync` replaces only that managed directory.

## Ownership

Framework: `.agent-managed/agent-engineering-framework/**` and content between `agent-framework` markers in AGENTS.md. Project: AGENTS.md outside markers, manifest values, `.ai-memory.toml`, source, architecture, harness config, tests, and domain rules.

## Harnesses, profiles, memory

Codex and OpenCode load same managed core; adapters define discovery/capability only. `generic` is always installed; `flutter` and `laravel` contain reusable discovery/validation guidance only. Use ai-memory through targeted retrieval; current source and project rules win contradictions.

## Daily operation

For a simple task, load project rules, relevant profile, and source; remain single-agent. For uncertain or broad work, the orchestrator may dispatch Explorer, Implementer, Reviewer, and Verifier with bounded ownership. Handoffs use `GOAL/STATE/FILES/DECISIONS/VERIFY/RISKS/OPEN`; no transcript or chain-of-thought transfer.

## Add a profile or harness

Add `profiles/<name>.md` only for reusable technology discovery and validation. Add `harness/<name>.md` only for configuration discovery, tools, capability, and model-selection mechanics. Update `agent-kit` validation and tests. Product, company, language-specific architecture, and release rules do not belong in the core.

## Troubleshooting

Run `agent-kit doctor`. It reports incompatible majors, malformed/missing AGENTS markers, modified managed files, unavailable profile assets, absent ai-memory configuration, and whether the requested harness executable is on PATH. It never installs tools or rewrites project-owned content. `agent-kit sync` repairs only framework-owned managed assets and its marker block.

## Upgrades and teams

Commit consumer-managed files in project. A teammate clones project plus a compatible framework release, then runs `agent-kit doctor`. Projects declare `framework_version = "1"`; incompatible majors fail doctor. Future packaging can retain this contract.
