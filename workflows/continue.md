# Continue workflow

Intent: resume a feature or engineering task without repeating reliable discovery.

1. Resolve repository, project rules, manifest, selected profile, and the relevant `engineering-protocol` sections.
   Parse an optional provider selector from the command arguments: `auto`,
   `openai`, `opencode`, `openrouter`, or `copilot`. It is a constraint for
   this continuation, not a project rule and not a reason to skip gates.
2. For a named feature, read its persisted state and compact handoff first. With the default provider, run `python3 .agent-managed/agent-engineering-framework/state/state.py validate <feature>` and then `get <feature> --json`. A project may declare a compatible project-owned provider in its manifest. Query ai-memory only for a pending handoff, prior decision, failed approach, or unresolved context likely to affect the next action.
3. Reconcile historical evidence against current Git/worktree, task/spec artifacts, and relevant source. Current project rules and source win conflicts; investigate discrepancies.
4. Identify actual unfinished work, its risk/complexity, dependencies, and required gate. Do not restart completed work merely from user wording.
5. Before any dispatch, generate a model proposal with `agent-kit continue <task> --harness <active> --provider <name> --propose --json`. Present the role/model/effort/estimate matrix and its disabled alternatives. Dispatch only after explicit approval (`--approve <proposal-id>`), or the user's explicit `--yes`; manual `--model role=<model-id>` overrides apply only to this activity. A stale task/state/catalog hash requires a new proposal.
6. Give each role only the approved `ContextCapsule`: objective, acceptance criteria, relevant decisions and paths/diff, dependencies, known failures, required gates, and current Developer Closure. Do not replay the full conversation, all memory, or all skills. Resume through normal protocol orchestration and record the effective execution with `agent-kit dispatch record`.
7. Treat `Free usage exceeded`, quota, rate-limit, and unavailable-model responses as terminal child failures. Do not retry or wait indefinitely. Use only the fallback order already approved in the `DispatchPlan`; any other fallback requires a fresh proposal/approval. Named providers stay strict; only `auto` may cross providers.
8. A harness cannot execute another harness's agents. If the requested provider is unavailable in the active harness, record a compact handoff with the selected provider and resume in the appropriate harness; do not pretend to dispatch it locally or choose a different provider.
9. Verify before claiming completion. Developer must recreate closure after a relevant source change. Do not rerun an identical gate against unchanged scoped source; a repeated failure/no-progress or exhausted review budget is `blocked` plus `human_escalation`, not another automatic cycle. If work remains, leave a compact protocol handoff; never transfer transcripts or reasoning.

The framework state schema is portable; project extensions may add evidence but
cannot make harness session data authoritative. Gate commands and closure
authority remain project-owned.
