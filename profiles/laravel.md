# Laravel profile

Discover Composer, PHPUnit/Pest, PHP version, queue/config, migrations, database topology, CI, and local gate documents. Prefer repository commands such as discovered `php artisan test`, Composer, Pint, and frontend build commands; never invent them.

For Developer Closure, select checks by the affected behavior. After related
edits, format only changed PHP files once when applicable. Use analysis/lint
only for affected code and focused PHPUnit/Pest tests for changed behavior.
Copy/docs-only changes do not automatically require PHP checks. Full suites,
frontend builds, database gates or migration rehearsals require affected
contracts, explicit project/acceptance requirements or risk. Reuse current
evidence; rerun only checks invalidated by fixes. See `core/verification.md`.

Treat schema changes as rollout-sensitive: inspect existing data, deploy order, old clients, nullable/default strategy, locks/index cost, rollback, and database engine behavior. HTTP changes need existing request validation, authentication, authorization/scope, stable errors, response compatibility, and pagination/versioning where relevant. Assess transactions for related writes; assess idempotency, uniqueness, ordering, retries, after-commit behavior, and observability for retryable endpoints/jobs/imports. Queues need timeout/backoff/idempotency/failed-state handling. Domain and Farm policy stay project-owned.

The shared OpenCode QA adapter may execute read-only gate candidates: `php artisan test`, Pest/PHPUnit, and Pint's `--test` mode, plus Git diff/status diagnostics. It remains unable to edit source or canonical project artifacts.
