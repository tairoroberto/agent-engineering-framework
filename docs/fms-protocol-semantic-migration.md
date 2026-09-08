# FMS protocol semantic migration map

Inventory source: Farm `.agents/skills/fms-engineering-protocol`, Farm Codex/OpenCode adapters, deterministic tests. Classification is primary.

| Source | Rule | Class | Destination | Status | Action |
| --- | --- | --- | --- | --- | --- |
| SKILL Activate | project rules first; harnesses adapters | INVARIANT | `core/principles.md` | partial | rewrite |
| SKILL Memory/Resume | artifacts/evidence outrank sessions; no transcripts | INVARIANT | `core/memory.md`, `core/handoff.md` | partial | rewrite |
| SKILL State machine | Farm `.specs` phase/state persistence | PROJECT | Farm extension | existing | keep local |
| SKILL Adaptive Orchestrator | coordinator; dependency/risk/parallel control | INVARIANT | `core/orchestration.md` | partial | rewrite |
| SKILL routing details | task metadata, capability classes, risk floors | DEFAULT | protocol routing policy | missing | extract |
| SKILL Planner IDs/API/DB | Farm artifacts; Laravel API/migration detail | PROJECT/PROFILE | Farm extension / Laravel profile | partial | split |
| SKILL Developer | bounded task, tests, no self-approval | INVARIANT | delegation/implementer | partial | rewrite |
| SKILL Reviewer | fresh read-only evidence review | INVARIANT | reviewer/verification | partial | rewrite |
| SKILL QA | post-review adversarial validation | DEFAULT | verification | partial | rewrite |
| SKILL gates/Pint | Farm commands/Pint baseline | PROJECT | Farm extension | existing | keep local |
| SKILL worktrees | disjoint writes only; uncertain sequential | INVARIANT | orchestration | partial | rewrite |
| SKILL metrics | compact no-prompt/no-secret metrics | INVARIANT | security/memory | partial | rewrite |
| SKILL escalation | evidence-led bounded escalation | DEFAULT | verification | partial | rewrite |
| `references/handoffs.md` | dispatch/route/result/escalation contracts | INVARIANT | handoff | partial | rewrite |
| `routing-policy.json` | capability routing/review/risk/budget defaults | DEFAULT | shared skill reference | missing | extract |
| `state*.schema.json`, `state.py` | FMS feature state, ID grammar, FMS_HARNESS | PROJECT | Farm compatibility implementation | existing | keep local |
| `routing.py` | Farm Markdown parser, state sync, local mappings | PROJECT | Farm compatibility implementation | existing | keep local |
| Pint script/baseline | Laravel formatting-debt boundary | PROJECT | Farm extension | existing | keep local |
| validator/tests | Farm adapter/regression contract | PROJECT | Farm extension | existing | keep local |
| `.codex/*` | model/sandbox/agent TOML mapping | ADAPTER | Farm Codex adapter | existing | keep local |
| `.opencode/*` | provider/permission/agent syntax | ADAPTER | Farm OpenCode adapter | existing | keep local |
| Laravel HTTP/DB/queue | validation/auth/transactions/migrations/retries | PROFILE | Laravel profile | partial | expand |
| Copilot clauses | third-harness Farm rollout | OBSOLETE | Farm compatibility only | existing | do not migrate |
| generic prose in FMS adapters | compatibility duplication | OBSOLETE | wrapper pointers | conflicting | reduce |

## Decision

`core/` is canonical policy. `skills/engineering-protocol/` is activation index plus generic routing defaults; it does not restate core policy. Farm state/routing/Pint scripts remain local because persistent schema, paths, task grammar, evidence contract, and gate mapping are Farm-specific. Old skill becomes compatibility router.

## Capability comparison

| Capability | Old | New |
| --- | --- | --- |
| Task classification/risk | yes | shared default + Farm extension |
| Selective delegation/parallel safety | yes | core invariant |
| Orchestrator/Explorer/Implementer | partial | generic roles |
| Reviewer/Verifier separation | partial | generic roles |
| Caverman/handoff | yes | core canonical |
| Cross-harness | yes | managed skill + adapters |
| Model routing | yes | capability classes/local mappings |
| ai-memory | partial | targeted history protocol |
| Context efficiency | yes | progressive loading |
| Project isolation | partial | rules/source outrank memory |
| Team portability | no | managed sync + install registry |
