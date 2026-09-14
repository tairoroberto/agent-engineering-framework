<!-- agent-framework:start -->
Shared agent orchestration is managed by Agent Engineering Framework.

Read `.agent-framework.toml`, then only task-relevant documents under
`.agent-managed/agent-engineering-framework/`. This managed block and assets
define cross-project agent behavior. Project rules in this AGENTS.md outside
this block remain authoritative for this repository. Read `.ai-memory.toml`
before using ai-memory; memory is historical context, not engineering authority.

Use `skills/engineering-protocol/SKILL.md` for orchestration, delegation,
Caveman, review, verification, handoff, and ai-memory behavior.
For portable continuation, use the configured state provider; the framework
default is `state/state.py` with project data at `.specs/features/<id>/state.json`.
<!-- agent-framework:end -->
