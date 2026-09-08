# Continue workflow

Intent: resume a feature or engineering task without repeating reliable discovery.

1. Resolve repository, project rules, manifest, selected profile, and the relevant `engineering-protocol` sections.
2. For a named feature, read its persisted state and compact handoff first. Query ai-memory only for a pending handoff, prior decision, failed approach, or unresolved context likely to affect the next action.
3. Reconcile historical evidence against current Git/worktree, task/spec artifacts, and relevant source. Current project rules and source win conflicts; investigate discrepancies.
4. Identify actual unfinished work, its risk/complexity, dependencies, and required gate. Do not restart completed work merely from user wording.
5. Resume through normal protocol orchestration: single-agent by default; delegate only for useful uncertainty reduction, independent review, verification, or isolated work.
6. Verify before claiming completion. If work remains, leave a compact protocol handoff; never transfer transcripts or reasoning.

Project state format, gate commands, and closure authority remain project-owned.
