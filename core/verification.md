# Verification

Project rules select commands and acceptance depth. Profiles provide discovery guidance only. Implementers run targeted gates; independent review and verification occur when scope/risk warrants them. A passing command proves only that command. Record command, result, scope, executor, and the evaluated source boundary.

Developer Closure is technical readiness, never self-approval. Before review, the
Developer runs the task-required conceptual gates: `format`,
`static-analysis`, `lint`, `focused-tests`, `required-tests`, or `build`.
Projects resolve them to real commands. A closure is valid only when every
required gate is PASS or explicitly SKIP for the same scoped source. Formatting
is Developer-only; if it changes source, affected gates run against the new
source. Reviewer and QA never format source.

Reuse a prior PASS only when gate class, command, and explicit task boundary
fingerprint are identical. A recorded identical FAIL is no reason to rerun
automatically. It is `NO_PROGRESS` and follows the convergence budget. Missing
or ambiguous ownership means execute normally and do not deduplicate. Provider,
quota, tool, infrastructure, baseline, and external-worktree failures are
classified separately; they never consume code-convergence budget.

Before a global gate, record the worktree and task boundary. If it fails only on a
path outside the dispatched task's owned paths/diff, report
`EXTERNAL_DIRTY_WORKTREE` with the path and command. It blocks a *clean
worktree/global-release* verdict, but is not a defect or task-gate failure for
the evaluated task. Do not edit, format, revert, or absorb that other work.
The Orchestrator must retain the scoped PASS/FAIL evidence and schedule the
unrelated task or a clean-worktree gate separately. If ownership cannot be
shown, treat the gate as BLOCKED rather than guessing.

Reviewer checks requirement fit, correctness, architecture, regression, unnecessary complexity, and relevant security/data/concurrency concerns. It returns one complete evidence-bearing finding batch per round: `BLOCKER`, `MAJOR`, or `MINOR`. BLOCKER/MAJOR may reopen Developer; MINOR records an observation but does not reopen automatically. Verifier checks test/build/analyze/lint/acceptance and failure behavior. High-risk work requires independent reviewer plus adversarial verification where feasible. Missing required execution is BLOCKED, never PASS. Preserve evidence across harnesses; re-run only stale or changed-scope evidence.
