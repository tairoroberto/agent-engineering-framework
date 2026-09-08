# Verification

Project rules select commands and acceptance depth. Profiles provide discovery guidance only. Implementers run targeted gates; independent review and verification occur when scope/risk warrants them. A passing command proves only that command. Record command, result, scope.

Reviewer checks requirement fit, correctness, architecture, regression, unnecessary complexity, and relevant security/data/concurrency concerns. Verifier checks test/build/analyze/lint/acceptance and failure behavior. High-risk work requires independent reviewer plus adversarial verification where feasible. Missing required execution is BLOCKED, never PASS. Preserve evidence across harnesses; re-run only stale or changed-scope evidence.
