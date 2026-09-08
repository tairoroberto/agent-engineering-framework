# Farm reference migration map

Classified from Farm's `AGENTS.md`, `.agents/skills/fms-engineering-protocol/`, `.opencode/`, `.codex/`, `.github/`, `.specs/features/shared-engineering-protocol/`, and validation scripts.

| Class | Framework destination | Farm disposition |
| --- | --- | --- |
| Generic | `core/`, `agents/`, `harness/`, `templates/`, `bin/agent-kit` | Consume managed copy; do not define as Farm authority |
| Laravel generic | `profiles/laravel.md` | Farm keeps stricter local rules/gates where needed |
| Farm-specific | Farm AGENTS, FMS skill, `.specs`, `docs/engineering-gates.md` | Keep: task state model, routing policy, PostgreSQL gate, domain/tenant/API rules |
| Harness-specific | `harness/*.md` | Existing `.codex`, `.opencode`, `.github` remain mappings/config only |
| Obsolete/duplicated | Generic prose duplicated in Farm adapters | Retained as compatibility pointers during first migration; no new generic policy there |

## Compatibility decision

Farm remains operational because its state/routing scripts and harness adapters stay local. They are a Farm spec-driven extension, not the reusable framework core. The managed block loads generic semantics before the FMS extension; existing adapters continue to call Farm's exact state and gate commands.
