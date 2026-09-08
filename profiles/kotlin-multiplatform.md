# Kotlin Multiplatform profile

Discover Gradle wrapper, version catalog, module/source-set layout, Compose Multiplatform use, platform targets, CI, and existing test conventions before changes. Prefer repository tasks and wrappers; never invent Gradle commands.

Typical commands to verify from the repository: `./gradlew test`, target-specific test tasks, lint/static analysis, Android assemble/instrumented tests, and iOS framework/link tests. Run only relevant project-defined gates.

Keep shared domain logic in appropriate common source sets; use `expect`/`actual` only for real platform differences. Review dependency/API compatibility across declared targets, platform threading/lifecycle behavior, serialization, time zones, offline persistence, and migration behavior when changed. Platform architecture, SDK integrations, release policy, and product rules remain project-owned.
