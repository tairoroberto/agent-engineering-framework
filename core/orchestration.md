# Orchestration

Progressive load: project rules -> manifest -> relevant framework capability -> targeted memory -> relevant source. Do not load every framework file, entire repository, or full memory dump.

Orchestrator decides single-agent or delegated execution. Simple, clear work stays single-agent. Delegate only for independent exploration/review/verification, isolated implementation, specialist analysis, or meaningful uncertainty reduction.

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
resolve it through the active harness `routing.json`. Resolve Reviewer and QA
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

A quota, rate-limit, or unavailable-model response is terminal for that child:
do not retry it or wait indefinitely. Use only the fallback order already
approved in the plan. A different fallback requires approval; a named provider
stays strict and only `auto` may change provider. If the harness cannot cancel a
pending child, record it as blocked/cancelled, prevent dependent dispatch, and
tell the operator the exact UI cancellation needed. No candidate means
execution is blocked while classification and required gates stay unchanged.
