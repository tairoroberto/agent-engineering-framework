---
description: "Plan and implement a feature with proportionate engineering rigor."
agent: orchestrator
---

<!-- agent-framework-command:start workflow=feature -->
Load `.agent-managed/agent-engineering-framework/workflows/feature.md`.
Load only the relevant engineering-protocol, profile, and project rules it routes to.
This is a generated adapter; do not redefine workflow semantics here.
Intent or feature reference: `$ARGUMENTS`.
Optional execution-provider selector: `<feature-or-intent> [auto|openai|opencode|openrouter|copilot|claude]` or `--provider=<name>`.
Before any Task dispatch, run `agent-kit feature $ARGUMENTS --harness opencode --propose --json`, present the proposal, and dispatch only an explicitly approved DispatchPlan.
Provider is a hard dispatch constraint: resolve before Task; dispatch only the exact returned `exec.agent` with `PROVIDER: exec.provider`. If this cannot be done, stop without a production dispatch.
<!-- agent-framework-command:end -->
