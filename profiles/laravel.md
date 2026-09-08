# Laravel profile

Discover Composer, PHPUnit/Pest, PHP version, queue/config, migrations, database topology, CI, and local gate documents. Prefer repository commands such as discovered `php artisan test`, Composer, Pint, and frontend build commands; never invent them.

Treat schema changes as rollout-sensitive: inspect existing data, deploy order, old clients, nullable/default strategy, locks/index cost, rollback, and database engine behavior. HTTP changes need existing request validation, authentication, authorization/scope, stable errors, response compatibility, and pagination/versioning where relevant. Assess transactions for related writes; assess idempotency, uniqueness, ordering, retries, after-commit behavior, and observability for retryable endpoints/jobs/imports. Queues need timeout/backoff/idempotency/failed-state handling. Domain and Farm policy stay project-owned.
