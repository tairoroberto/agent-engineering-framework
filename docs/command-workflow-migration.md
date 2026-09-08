# Command workflow migration

## Farm reference audit

| Command | Old OpenCode behavior | Classification | New owner |
| --- | --- | --- | --- |
| `/continue` | Read Farm feature state, reconcile Git/tasks/handoff, resume phase | Shared continuation sequence; Farm state format | `workflows/continue.md` + Farm extension |
| `/feature` | Load skills, route/planning/review/QA, use Farm state | Shared feature sequence; Farm routing/state/gates | `workflows/feature.md` + Farm extension |
| `/review` | Fresh review, QA/final gate, close Farm state | Shared independent review; Farm closure | `workflows/review.md` + manifest hook |
| `/status` | Render Farm state/tasks/gates | Project-only | Farm `.opencode/commands/status.md` |

Farm Codex supplied agent profiles and routing, not project slash-command definitions. Current Codex supports reusable global custom prompts, so `agent-kit install` generates `/prompts:continue`, `/prompts:feature`, and `/prompts:review`. OpenCode continues to expose `/continue`, `/feature`, and `/review` from generated project adapters.

## Ownership and drift correction

Canonical workflow sequencing, selective delegation, Caverman, memory use, review, verification, and handoff live once in `workflows/` plus `engineering-protocol`/`core`. OpenCode adapters contain only metadata, workflow routing, arguments, and an optional declared project hook. Codex prompts contain the same route, using Codex's global prompt discovery. Farm-specific state closure is an explicit `[workflows.review]` manifest hook, not duplicated review policy.

The prior OpenCode commands drifted: `/continue` performed detailed reconciliation while `/feature` and `/review` restated different fragments of policy; Codex had no equivalent project command surface. The canonical workflows normalize those shared semantics while retaining Farm's state/gate implementation locally.

## Semantic parity

| Capability | Old Codex | Old OpenCode | Shared workflows |
| --- | --- | --- | --- |
| Scope discovery | Agent instruction | `/feature` | Yes: `feature` |
| Selective delegation | Agent routing | `/feature` | Yes: protocol-composed |
| Compact handoffs | Protocol | `/continue` | Yes: protocol-composed |
| Git/source reconciliation | Agent/protocol | `/continue` | Yes: `continue` |
| Independent review | Agent profile | `/review` | Yes: `review` |
| Verifier separation | Protocol | `/review` | Yes: `review` + protocol |
| Project gate selection | Farm rules | Farm rules | Yes: profile/project layer |
| ai-memory historical retrieval | Managed routing | Indirect | Yes: targeted, non-authoritative |
| Farm state close | Script/agent | `/review` script handoff | Yes: declared project hook |
| Reuse across projects | No command UX | No | Yes: generated adapters |
| Portable consumer path | N/A | Project-local | Yes: managed relative path |

## Validation contract

Run `agent-kit install` once per machine for Codex prompts. For every consumer run `agent-kit doctor`, then `agent-kit sync` twice; the second sync must report all generated adapters unchanged. The Farm protocol regression suite additionally checks that each OpenCode command routes to its managed workflow and that Farm `/review` retains its state-close hook.
