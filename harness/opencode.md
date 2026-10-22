# OpenCode adapter

Adapter scope only: discover project `AGENTS.md`, `.agent-framework.toml`, `.agent-managed/agent-engineering-framework/`, `.opencode/`, `opencode.json`, and available skills/agents. OpenCode provider/model/config syntax remains execution detail. Core roles, review, verification, memory, and project policy remain shared.


## OpenCode 1/2

Keep one harness and generated V1-compatible configuration for both majors;
V2 translates supported V1 fields in memory. Never convert shared files to
V2-only syntax while V1 consumes them. See `docs/opencode-compatibility.md`.

V1 delegation/shell tools are `task`/`bash`; V2 uses `subagent`/`shell`.
Preserve route/provider contracts and role boundaries regardless of tool name.
Use explicit `external_directory: ask` in legacy agent permissions to preserve
the workspace boundary on V2. V2 has no LSP runtime; project gates supply
analysis/typecheck/compiler evidence.

V1 model discovery supports `models --verbose` and provider arguments. V2 uses
`models --standalone` and local provider filtering. V2 automated dispatch uses
`run --standalone` so a shared service cannot hide launch environment changes.
V1 plugins and server API clients require separate V2 migration. MCP presence
alone proves no lifecycle hook compatibility. Native runtime inspection is
separate from the offline adapter contract checks performed by `doctor`.
