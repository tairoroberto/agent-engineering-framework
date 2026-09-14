# Feature workflow

Intent: take a product or technical feature from requested outcome to proportionately verified result.

1. Load project rules, manifest, selected profile, and only relevant `engineering-protocol` sections.
2. Use targeted ai-memory only when a prior decision, subsystem history, failed approach, or handoff could change the scope. Treat it as historical evidence, never authority.
3. Discover the relevant source and documentation. Define scope, acceptance outcome, complexity, risk, dependencies, and required verification before implementation. Before dispatch, generate and present `agent-kit feature <feature-or-intent> --harness <active> --provider <name> --propose --json`; execute only its approved `DispatchPlan`. Low-confidence classification blocks until complexity and risk are declared.
4. Keep simple, clear, local work single-agent. For complex, uncertain, independently parallelizable, or review-sensitive work, have the orchestrator selectively delegate with bounded ownership and Caveman handoffs.
5. Implement through project architecture and profile guidance. Developer runs task-required gates, records scoped closure facts, and requests review only after the closure is valid. Before rerunning a gate, use the convergence decision; do not repeat an identical PASS or FAIL against unchanged scoped source. Send each role only its compact `ContextCapsule`; project rules select tests, commands, releases, and business constraints. Record effective model, effort, consumption, result, and gates as a fact-only `DispatchReceipt`.
6. Apply independent review and verifier checks when the protocol/risk/project requires them. Reviewer returns one complete finding batch. BLOCKER/MAJOR findings go to one Developer fix batch; MINOR findings do not reopen automatically. QA is selected only when risk, task metadata, project policy, or acceptance requires it. Neither role substitutes for the other.
7. Record only authorized durable memory and leave a compact handoff when continuation is needed.

Do not force ceremony, delegation, or a full memory read for trivial work.
