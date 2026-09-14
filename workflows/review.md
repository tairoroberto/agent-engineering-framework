# Review workflow

Intent: independently assess a requested change or feature against current evidence.

1. Load project rules, manifest, selected profile, and relevant `engineering-protocol` review/verification sections.
2. Establish scope from the requested range, current diff, affected requirements, available verification evidence, and Developer Closure. Refuse review when required closure is absent or stale. Query ai-memory only if a prior architectural decision or known failure mode materially affects review. Generate `agent-kit review <scope> --harness <active> --provider <name> --propose --json` and require explicit approval of Reviewer/QA models before dispatch when QA is required.
3. Review independently from implementation reasoning where the harness permits. Evaluate requirement fit, correctness, architecture, regression and edge-case risk, security/data/concurrency concerns where relevant, maintainability, unnecessary complexity, tests, and missing verification evidence.
4. Pass only the approved `ContextCapsule`, never the complete implementation transcript or reasoning. Return one complete, evidence-bearing finding batch only: `BLOCKER`, `MAJOR`, `MINOR`; cite requirement, file/line, scenario, expected and actual behavior. Historical `CRITICAL/HIGH/MEDIUM/LOW` labels are normalized by the state owner. Say explicitly when there are no material findings.
5. Keep reviewer and verifier distinct. A review finding is not an executable gate; passing tests are not a review verdict. Run or request project-required verification separately.
6. Route fixes and closure to the orchestrator/project state owner. Reviewer and QA never silently fix findings or write `.specs`/validation artifacts. The Orchestrator records canonical evidence after independently reconciling their reports.

If the project manifest declares a reviewed post-workflow hook, run it only after the workflow's applicable review and verification prerequisites. The hook is project-owned and cannot turn missing evidence into PASS.
