# Changelog

## 1.7.0

- Add Execution Convergence and Developer Closure to portable task state without introducing a parallel state machine.
- Let Developer run discovered project gates, including touched-file formatting, while Reviewer remains read-only and QA remains non-mutating.
- Record scoped gate/source/failure facts, reuse an identical PASS, and escalate an identical FAIL/no-progress instead of cycling automatically.
- Require one complete `BLOCKER`/`MAJOR`/`MINOR` review batch; bound review/fix rounds and use `blocked` plus `human_escalation` on exhaustion.
- Keep provider, tool, baseline, and external-dirty-worktree failures outside the code-convergence budget.
- Keep LOW-risk fast paths to Developer Closure plus Reviewer unless QA is explicitly required by risk, task verification, project policy, or acceptance.

## 1.6.0

- Bootstrap project-owned `.ai-memory.toml` idempotently with profile safety defaults, identity inference, doctor validation, and diff visibility.
- Add transactional `agent-kit init --force` repair with model preflight, recoverable inventory backups, ownership-ledger pruning, doctor validation, and rollback.
- Add a fingerprinted four-harness model catalog plus deterministic classification that blocks low-confidence inference instead of silently choosing MEDIUM/HIGH.
- Add per-activity model proposals, explicit approval, stronger-model overrides, compact context capsules, stale-input protection, strict providers, approved fallbacks, fact-only dispatch receipts, and usage reporting.
- Generate bounded adapters and workflow entry points for OpenCode, Codex, GitHub Copilot, and Claude Code.
- Leave OpenCode `steps` unset so the Orchestrator is not forcibly stopped mid-activity; cost control comes from approved routing, compact context, effort, and receipts.
- Use verified cost/token history to reorder eligible candidates without reducing model floors, review independence, safety, or gates.
- Offer an init-only `y/N` bootstrap for an idempotent `agent-kit` PATH entry in `.zshrc` or `.bash_profile`.
- Add `agent-kit tasks list` with feature/status/all/JSON filters and a Portuguese step-by-step operating guide.

## 1.5.1

- Make QA classify global gate failures outside a dispatched task boundary as `EXTERNAL_DIRTY_WORKTREE`, not a false task defect.

## 1.5.0

- Permit OpenCode QA to execute a small profile-specific allow-list of non-mutating verification gates while retaining read-only artifact permissions.

## 1.4.9

- Make managed harness synchronization preflight all adapters before writing.
- Add explicit, backed-up `agent-kit sync --replace-managed` recovery for a locally altered framework-owned adapter.

## 1.4.8

- Route Reviewer and QA through provider-aware candidates, including managed OpenAI OpenCode profiles.
- Treat quota, rate-limit, and unavailable-model errors as terminal child failures; document bounded fallback and pending-child handling.

## 1.4.7

- Make provider selection a hard OpenCode dispatch contract and add developer-side provider mismatch refusal.

## 1.4.6

- Require generated OpenCode orchestrators to forward `/continue` provider selection into formal routing.

## 1.4.5

- Add managed OpenCode OpenAI developer profiles and routing candidates using locally discovered OpenAI model IDs.

## 1.4.4

- Accept established compact task IDs (`T1` through `T999`) alongside zero-padded task IDs in portable routing/state.

## 1.4.3

- Add strict optional provider selection (`auto`, `openai`, `opencode`, `openrouter`, `copilot`) to continuation and formal routing.

## 1.4.2

- Add ordered, harness-local model candidates and safe quota/unavailability failover for formal task dispatch.

## 1.4.1

- Add deterministic harness resolution from portable task `modelClass` to the configured local agent/model.
- Generate and validate Codex/OpenCode routing maps with `agent-kit`.

## 1.4.0

- Promote the full V2 portable state runner from the Farm reference implementation into the framework.
- Support optional project routing/closure extensions without making a project own state runtime.
- Convert Farm state scripts into thin compatibility wrappers over the managed framework runtime.

## 1.3.0

- Add a versioned, harness-neutral portable feature-state baseline under `state/`.
- Add stdlib state creation, validation, compact gate/handoff recording, and cross-harness continuation tests.
- Let projects retain an audited compatible state provider through `[state] provider = "project"`.

## 1.2.0

- Make OpenCode and Codex agent profiles, harness configuration, and OpenCode gates adapters managed `agent-kit` assets.
- Preserve audited project-specific harness implementations through an explicit manifest override.

## 1.1.0

- Add canonical `continue`, `feature`, and `review` workflows.
- Generate thin OpenCode project command adapters and managed Codex global prompt adapters.
- Extend `agent-kit` status, diff, and doctor with workflow/adapter checks.

## 1.0.0

- Initial local-first framework: roles, Caveman, handoff, verification, memory protocol, Codex/OpenCode adapters, Flutter/Laravel profiles, `agent-kit`.
