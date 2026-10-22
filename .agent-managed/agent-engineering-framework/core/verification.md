# Verification

Project rules select commands and acceptance depth. Profiles provide discovery guidance only. Implementers run targeted gates; independent review and verification occur when scope/risk warrants them. A passing command proves only that command. Record command, result, scope, executor, and the evaluated source boundary.

Choose the smallest verification that can detect a defect in the changed
behavior. Gate classes (`format`, `static-analysis`, `lint`, `focused-tests`,
`required-tests`, `build`) are options, not a mandatory checklist. Select the
applicable subset from acceptance, affected code/dependencies, risk and explicit
project requirements. A configured tool or an available test suite alone does
not make it relevant. Do not add tests for reversible copy, documentation or
mechanical changes when they would only mirror the edit; inspect the diff and
run an applicable structural check instead. Preserve explicitly required gates.

Implement the approved work before routine validation. Group related edits and
run each relevant command once at the task/batch boundary; validate earlier only
when a dependency, risky assumption or project rule needs the result to proceed.
A shared command may supply evidence for several tasks only when its actual
coverage and final source boundaries are recorded for each; do not rerun it just
to produce another receipt. Do not mark a task complete before its required
acceptance and evidence are satisfied.

Formatting is Developer-only and applies only to changed files supported by the
project formatter. Run it once after the edits, before affected checks; do not
alternate formatter and formatting-check commands or format the whole repository
for a local change. Reviewer and QA reuse current formatting evidence. If no
applicable formatter or relevant tests exist, record that compactly; do not
invent a command or run unrelated tests to fill a checklist.

Developer Closure is technical readiness, never self-approval. For formal state,
require only selected gate classes; PASS or an explicitly justified SKIP must
refer to the same scoped source. A project-required gate cannot be skipped just
to save time. A small local task needs concise inline evidence, not additional
planning/state ceremony unless the project requires it.

On a concrete failure, fix the cause in one bounded batch and rerun only the
checks invalidated by that fix. Broaden to a full suite/build only for explicit
project requirements, affected shared contracts/dependencies, high risk, or a
failure that focused checks cannot resolve; state the reason once. After the
selected gates pass, proceed to closure instead of adding speculative checks.

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
