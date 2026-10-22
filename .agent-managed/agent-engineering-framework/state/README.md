# Portable feature state

State is project-local, portable evidence for continuing a feature across
Codex, OpenCode, GitHub Copilot, Claude Code, or humans.

```text
.specs/features/<feature>/state.json
```

The framework owns this V2 contract and runner; the project owns its source, rules,
commands, and any reviewed extension. State is not a transcript, prompt log,
chain-of-thought store, secret store, or harness session store.

## Commands

Run from any directory inside the consumer repository:

```bash
python3 .agent-managed/agent-engineering-framework/state/state.py new <feature>
python3 .agent-managed/agent-engineering-framework/state/state.py validate <feature>
python3 .agent-managed/agent-engineering-framework/state/state.py get <feature> --json
python3 .agent-managed/agent-engineering-framework/state/state.py mark <feature> <task> <status>
python3 .agent-managed/agent-engineering-framework/state/state.py gate <feature> <gate> <PASS|FAIL|SKIP|EXTERNAL> --command "<command>" --evidence "<compact evidence>"
python3 .agent-managed/agent-engineering-framework/state/state.py gate-decision <feature> <task> <kind> --command "<command>" --scope <path>
python3 .agent-managed/agent-engineering-framework/state/state.py developer-close <feature> <task> --require format,static-analysis,focused-tests --scope <path>
python3 .agent-managed/agent-engineering-framework/state/state.py review-start <feature> <task>
python3 .agent-managed/agent-engineering-framework/state/state.py review-result <feature> <task> PASS --findings '[]'
python3 .agent-managed/agent-engineering-framework/state/state.py handoff <feature> '<json object>'
```

Only the Orchestrator/project state owner updates canonical state. Workers,
Reviewer, and QA return compact evidence to that owner. On resume, validate
state first, then reconcile it with current Git, source, project rules, and
required gates. Those current facts override stale state.

`lastHarness` is diagnostic metadata only. It never decides which harness can
resume, and it never overrides source or project rules.

Projects may provide a routing/closure extension through
`AGENT_FRAMEWORK_ROUTING_MODULE`. The extension validates only project task
metadata at closure time; it never owns the state runtime or adds harness state.

## Model catalog and approved activity selection

For a formal `tasks.md`, routing derives complexity, risk, capabilities and
required verification into a portable `modelClass`. Declared metadata wins,
then valid persisted classification, then deterministic inference; low
confidence blocks. The shared policy never contains a vendor/model ID. The
selected harness resolves that class through its generated local mapping and
fingerprinted catalog:

```bash
python3 .agent-managed/agent-engineering-framework/state/routing.py validate .specs/features/<feature>/tasks.md
python3 .agent-managed/agent-engineering-framework/state/routing.py sync <feature>
python3 .agent-managed/agent-engineering-framework/state/routing.py resolve .specs/features/<feature>/tasks.md T001 opencode
agent-kit catalog show
agent-kit continue T001 --harness opencode --provider openai --propose --json
agent-kit continue --approve <proposal-id> --model developer=<stronger-model>
```

`resolve` returns the concrete agent/model/reasoning effort from the active
harness mapping. An absent class or low-confidence classification is a visible
blocker. Before delegation, a hash-bound `ModelProposal` lists eligible and
disabled alternatives for each role. Explicit approval produces a
`DispatchPlan`; overrides are activity-local and stronger choices do not alter
classification. Each role receives only its `ContextCapsule`.

When a harness returns a quota or availability error, retain the task class and
use only a fallback already approved in the plan. Record execution through
`agent-kit dispatch record`; the fact-only receipt and compact metrics can
improve later cost/token ordering without storing prompts, sessions, transcripts,
reasoning, or credentials. No approved candidate means blocked evidence and a
new proposal, never arbitrary fallback or weaker verification.

Task IDs may preserve either an existing compact sequence (`T1`, `T34`) or a
zero-padded sequence (`T001`, `T034`). The framework never renumbers them.

## Execution convergence

The state runtime records Developer Closure without turning it into
self-approval. A Developer runs project-selected conceptual gate classes,
typically `format`, `static-analysis`, `lint`, `focused-tests`,
`required-tests`, or `build`, then closes only the required passing/SKIP gates
for the same explicit task scope.

`gate-decision` hashes the current declared source boundary with the Developer
role, gate class, and command. An identical PASS is reused. An identical FAIL
is a no-progress stop and escalates according to the feature execution policy.
A changed scoped file creates a new fingerprint and permits a new run. `EXTERNAL` gate evidence
for provider/tool/infrastructure/baseline/dirty-worktree conditions never
consumes this budget.

Reviewer opens a counted round only after a valid closure. It returns one batch
of `BLOCKER`, `MAJOR`, or `MINOR` findings. BLOCKER/MAJOR can create one
Developer fix batch; MINOR observations do not reopen automatically. Exhausted
review or no-progress budget uses existing `blocked` and `human_escalation`
states with compact factual reason/options.
