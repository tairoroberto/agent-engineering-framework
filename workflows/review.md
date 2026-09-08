# Review workflow

Intent: independently assess a requested change or feature against current evidence.

1. Load project rules, manifest, selected profile, and relevant `engineering-protocol` review/verification sections.
2. Establish scope from the requested range, current diff, affected requirements, and available verification evidence. Query ai-memory only if a prior architectural decision or known failure mode materially affects review.
3. Review independently from implementation reasoning where the harness permits. Evaluate requirement fit, correctness, architecture, regression and edge-case risk, security/data/concurrency concerns where relevant, maintainability, unnecessary complexity, tests, and missing verification evidence.
4. Return prioritized, evidence-bearing findings only: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`; cite requirement, file/line, scenario, expected and actual behavior. Say explicitly when there are no material findings.
5. Keep reviewer and verifier distinct. A review finding is not an executable gate; passing tests are not a review verdict. Run or request project-required verification separately.
6. Route fixes and closure to the orchestrator/project state owner. Reviewer never silently fixes its own findings.

If the project manifest declares a reviewed post-workflow hook, run it only after the workflow's applicable review and verification prerequisites. The hook is project-owned and cannot turn missing evidence into PASS.
