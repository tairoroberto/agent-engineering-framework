# Orchestration

Progressive load: project rules -> manifest -> relevant framework capability -> targeted memory -> relevant source. Do not load every framework file, entire repository, or full memory dump.

Orchestrator decides single-agent or delegated execution. Simple, clear work stays single-agent. Delegate only for independent exploration/review/verification, isolated implementation, specialist analysis, or meaningful uncertainty reduction.

Once the implementation plan and tasks are accepted, execute all ready tasks in
dependency order through completion, relevant validation and bounded fixes. Do
not stop after each task to ask whether to continue, replan accepted work, or
rediscover unchanged context. Pause only for a real blocker, a material scope or
risk change, or an action outside the existing authorization. Reuse an unchanged
approved model/dispatch contract; this does not bypass stale-plan checks or
authorize unapproved models, providers or external actions.

Choose verification from impact, not tool availability. Group related edits
before routine checks, reuse current evidence and stop when acceptance passes.
`core/verification.md` owns gate selection and rerun rules. Keep progress and
closure compact: changed behavior, relevant evidence and actual blockers only.

Dispatch includes goal, bounded ownership, dependencies, expected evidence, verification gate, write/commit authority. Orchestrator alone reconciles shared task state and integrates results. Subagents never redefine scope.

Classify complexity (LOW/MEDIUM/HIGH) separately from risk (LOW/MEDIUM/HIGH/CRITICAL). Capability/risk floors can raise model or verification depth; budget mode cannot lower them. Parallel work requires passed dependencies, explicit parallel intent, disjoint write/conflict boundaries, and capacity. Missing evidence or uncertain conflict means sequential.

Convergence is semantic, not a turn/`steps` cap. The state execution policy
bounds review/fix rounds, repeated same-gate failures, and no-progress rounds.
Before dispatching review, require a valid Developer Closure. On a complete
BLOCKER/MAJOR batch, send one bounded fix batch only to Developer, then validate
again. On an exhausted budget or unchanged source+gate+failure, set task
`blocked`, feature `human_escalation`, and a compact operator action. Do not
retry indefinitely. Provider circuit breakers and external failures remain
separate from this budget.

For formal tasks, use the shared router to derive a portable `modelClass`, then
resolve it through the active harness `routing.json`. An empty class is a
routing gap, not proof of model incapability. The resolver automatically checks
available catalog models with existing adapters in the same role family and
selects the cheapest eligible one, retaining the task floor, named provider and
excluded failures. Cost uses published/project rates when known, otherwise the
declared cost tier; unknown prices are not claimed as measured savings.
If the catalog model lacks an adapter, run `agent-kit sync` once to regenerate
framework-owned candidates; refresh a stale catalog once with
`agent-kit sync --refresh-models`. Preserve project-owned edits and reconcile
stale execution contracts. Do not repeatedly refresh or hand-edit task risk,
provider, required gates or failed-model exclusions to force a match.
 Resolve Reviewer and QA
through their `reviewClasses` and `qaClasses` with the same provider selector.
The router prioritizes declared metadata, then valid persisted classification,
then deterministic inference. Low-confidence inference blocks dispatch instead
of silently assuming MEDIUM/HIGH. Capability floors can only raise the class.

Every delegated activity starts as a hash-bound `ModelProposal`. The user must
approve it before it becomes a `DispatchPlan`; per-role overrides never alter
the manifest or a later activity. The Orchestrator is locked to the configured
strong control-plane model and uses low effort normally, medium only for
HIGH/CRITICAL risk. Developer and QA default to low effort; Reviewer to medium.
No role receives xhigh/max automatically.

Dispatch only the role's compact `ContextCapsule`: objective, acceptance,
decisions, paths/diff, dependencies, known failures, and gates. Record effective
model, effort, token/cache/cost facts, outcome, gates, and mismatch in a
`DispatchReceipt`; never persist prompts, transcripts, reasoning, sessions, or
credentials. Verified historical consumption may reorder candidates within the
same floor, but never lower capability, independence, security, or gates.

A quota, rate-limit, unavailable-model, or context-window response is terminal for that child:
do not retry it or wait indefinitely. Use only the fallback order already
approved in the plan, including its eligible provider-local alternatives.
Repairing an empty class to an already covered capable model needs no extra
confirmation. A model outside the approved activity still requires a reconciled
proposal; a named provider stays strict and only `auto` may change provider. If the harness cannot cancel a
pending child, record it as blocked/cancelled, prevent dependent dispatch, and
tell the operator the exact UI cancellation needed. The launcher records only
the failure category and reported retry delay. No candidate creates a
recoverable capacity wait while classification and required gates stay unchanged;
it never consumes the code-convergence budget.
