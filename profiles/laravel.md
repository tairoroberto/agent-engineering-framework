# Laravel profile

Discover Composer, PHPUnit/Pest, PHP version, queue/config, migrations, database topology, CI, and local gate documents. Prefer repository commands such as discovered `php artisan test`, Composer, Pint, and frontend build commands; never invent them.

For Developer Closure, discover the smallest project-approved sequence for the
touched scope: format touched PHP when permitted, run static analysis/lint when
configured, then focused PHPUnit/Pest coverage. Use a full suite, frontend
build, database gate, or migration rehearsal only when required by risk,
project policy, or acceptance. Record command/result/scope facts.

Treat schema changes as rollout-sensitive: inspect existing data, deploy order, old clients, nullable/default strategy, locks/index cost, rollback, and database engine behavior. HTTP changes need existing request validation, authentication, authorization/scope, stable errors, response compatibility, and pagination/versioning where relevant. Assess transactions for related writes; assess idempotency, uniqueness, ordering, retries, after-commit behavior, and observability for retryable endpoints/jobs/imports. Queues need timeout/backoff/idempotency/failed-state handling. Domain and Farm policy stay project-owned.

The shared OpenCode QA adapter may execute read-only gate candidates: `php artisan test`, Pest/PHPUnit, and Pint's `--test` mode, plus Git diff/status diagnostics. It remains unable to edit source or canonical project artifacts.
