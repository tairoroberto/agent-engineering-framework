# Delegation

Use one role per bounded responsibility. Explorer is read-first. Implementer changes only assigned paths. Reviewer is fresh, independent, read-only. Verifier runs applicable project/profile commands and acceptance checks. Reviewer evaluates implementation; Verifier executes requirements/gates. Do not collapse roles when independent evidence matters.

Dispatch minimum context: goal, rules/paths, task boundary, dependencies, outcome, gate, authority. Developer receives one task and may not alter requirements, architecture decisions, canonical state, or tests to conceal failure. Reviewer never fixes or contacts Developer directly. Return compact evidence, not reasoning or transcripts.
