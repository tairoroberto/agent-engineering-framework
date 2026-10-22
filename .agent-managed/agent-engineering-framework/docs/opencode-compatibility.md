# OpenCode 1 and 2 compatibility

The framework uses one `opencode` harness for both major versions. Generated
configuration stays in supported V1 syntax. OpenCode 2 normalizes it in memory;
no consumer configuration is rewritten to native V2-only syntax. Keep the
project's manifest provider policy and model lock across harness upgrades.

## Compatibility contract

| Area | Shared behavior | V2 difference |
| --- | --- | --- |
| Agents | `.opencode/agents/*.md`, explicit `mode`, qualified `model`, V1 `permission` | Native names are `agents`, `permissions`, `shell`, `subagent`; supported V1 definitions are translated |
| Skills | `skills.paths` plus `SKILL.md` with matching lowercase name and description | Native extra sources use a `skills` array; shared discovery still works |
| Workflows | `.opencode/commands/{continue,feature,review}.md`, `agent: orchestrator` | Existing Markdown commands remain supported |
| Model discovery | Provider IDs normalized locally, including `github-copilot` → `copilot` | `opencode models --standalone`, local provider filtering; no V1 `--verbose` or positional provider arguments |
| Dispatch | Fresh `run --format json --agent … --model …`; no session reuse or automatic permission approval | `--standalone` isolates each launch from the shared background service |
| Workspace access | Every generated agent explicitly asks before external-directory access | V2 otherwise allows external directories by default |
| Gates | Project lint, analysis, tests and compiler commands | V2 accepts LSP configuration but has no LSP runtime |
| Memory | MCP can use V1 `mcp.<name>` or native V2 `mcp.servers.<name>` | Plugin API changed; legacy plugin file presence cannot prove lifecycle hooks work |

The framework probes `opencode --version` with a bounded timeout. An unknown
version preserves legacy command behavior and is reported as unverified by
`doctor`; an unrecognized major is unsupported. Discovery failures do not imply
provider availability. Configured models remain configuration evidence, not
proof of authentication or account entitlement.

## Update a consumer

```sh
agent-kit sync
agent-kit doctor
agent-kit env --check
```

`sync` updates framework-owned adapters under the existing backup/ledger rules.
Manual changes are diagnosed rather than silently overwritten; inspect
`agent-kit diff` before using `sync --replace-managed` to replace them.
Project extensions and unrelated configuration remain project-owned. Do not
convert shared files to V2-only syntax while V1 still consumes them.

`doctor` validates generated route-to-agent references, modes, model format,
child delegation boundaries, explicit external-directory policy and project
skill frontmatter. It also reports local plugin migration risks, ignored
legacy settings and native V2 fields encountered on V1. These are offline
contract checks, not a full OpenCode schema validator or proof of effective
layered permissions. Global/system configuration may override project values.

## Verify the installed runtime

On V1, check `opencode agent list`, `opencode debug config`, and
`opencode models --verbose`. On V2, check `opencode debug agents`,
`opencode debug config`, and `opencode models --standalone`. Verify the
`orchestrator` primary agent, routed children, skills and `/continue`,
`/feature`, `/review` in the selected runtime. Debug output can include private
configuration: inspect locally and do not commit it.

Do not install or upgrade a global OpenCode binary merely to test compatibility.
Use isolated test installations and temporary projects when checking both majors.
An authenticated AI task, actual permission enforcement, MCP tool execution and
plugin lifecycle events require separate runtime acceptance evidence.
`agent-kit env` deliberately reports V2 ai-memory lifecycle integration as
partial until it can be verified through a supported runtime contract; it does
not claim an old `ai-memory.ts` file is compatible or rewrite external plugins.

## Reproducible native smoke test

```sh
python3 scripts/validate_opencode.py --binary opencode
python3 scripts/validate_opencode.py --binary /path/to/isolated-v1/opencode
```

This opt-in check creates a temporary consumer and isolated configuration/data,
checks all generated agents' models, effort and normalized role permissions,
finds the shared skill and three workflow commands, and stops its private V2
server afterwards. No AI prompt is sent. V2 registries initialize asynchronously;
the check waits for expected agents within a bounded readiness window. User
skill locations may still be discovered by OpenCode; their contents are never
printed. Network access and local server execution may require sandbox access.

## Recorded validation (2026-10-22)

| Runtime | Evidence | Result |
| --- | --- | --- |
| OpenCode 1.3.17, isolated npm installation | Native smoke: 21 generated agents, configured models/effort, role permissions, shared skill, three workflow commands | PASS |
| OpenCode 2.1.2, installed binary with temporary data/config | Same native smoke with normalized V2 permissions and private server | PASS |
| OpenCode 2.1.2 model discovery | Real `models --standalone` query, no provider/verbose arguments | PASS |
| Consumer major switch | Offline init on V1 → sync/doctor on V2, same config bytes, preserved project extension, malformed child mode rejected | PASS |

No paid/model inference, tool permission execution, authenticated provider task,
or ai-memory lifecycle event was exercised. Native checks prove discovery and
normalized metadata, not end-to-end AI behavior. Other V1/V2 releases require
the same smoke check; compatibility is not inferred for every patch release.

## Official references

- [V2 migration and compatibility guarantees](https://dev.opencode.ai/v2/docs/migrate-v1/)
- [V1 agents](https://opencode.ai/docs/agents/), [V2 agents](https://dev.opencode.ai/v2/docs/agents/)
- [V2 skills](https://dev.opencode.ai/v2/docs/skills/)
- [V2 CLI commands](https://dev.opencode.ai/v2/docs/cli/commands/)
- [V2 permissions](https://dev.opencode.ai/v2/docs/permissions/)
