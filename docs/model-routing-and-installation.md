# Installation, model routing, and activity approval

## Ownership

`agent-kit` owns the managed framework copy, its marked `AGENTS.md` block,
generated harness adapters, their checksum ledger, the model catalog lock, and
ephemeral proposal/plan/receipt files under `.agent-managed/`.

The project owns `.agent-framework.toml`, `.ai-memory.toml` immediately after
bootstrap, `.specs`, evidence, metrics, handoffs, source, tests, documentation,
workflow hooks, and every harness extension not present in the ledger. Neither
`sync` nor `init --force` rewrites an existing `.ai-memory.toml`.

## Initial installation and repair

```bash
agent-kit init --profile flutter
agent-kit init --profile laravel --harness opencode --harness claude
agent-kit init --force --yes
agent-kit init --force --reuse-model-lock --yes
agent-kit init --force --orchestrator-model gpt-5.6-sol --yes
```

With a valid manifest, forced initialization reuses its profile and harnesses
unless flags override them. Without a valid manifest, `--profile` and at least
one `--harness` are required. Non-interactive forced initialization requires
`--yes`.

Before changing the project, a forced reinstall stages the selected harness
mappings and validates the model catalog. It inventories affected paths, writes
a recoverable snapshot under `.agent-managed/backups/reinstall-<id>/`, repairs
managed assets, removes only obsolete ledger entries, and runs `doctor`. Any
failure restores the inventory. It never recursively removes `.opencode`,
`.codex`, `.github`, or `.claude`.

## ai-memory bootstrap

When `ai_memory = true`, `init`, `init --force`, and `sync` use the same
idempotent bootstrap. Output is `created`, `preserved`, `disabled`, or `invalid`.
Identity priority is explicit `--memory-workspace`/`--memory-project`, Git
remote/path inference, then normalized parent/repository names. Technology
profiles add sensitive-path defaults only during creation.

`doctor` fails on a missing or invalid enabled config and warns when minimum
`.env`, key, or secret protections are absent. It never repairs an existing
project-owned file. `diff` previews `create`, `preserve`, `disabled`, or
`invalid`.

## Catalog and classification

```bash
agent-kit catalog show
agent-kit catalog refresh
agent-kit catalog refresh --orchestrator-model <model-id>
agent-kit route explain T33 --harness opencode --provider openai
agent-kit route simulate T33 --harness opencode --provider openai --json
```

The lock records harness/provider, model ID, portable classes, capabilities,
supported effort data when known, context-window data when known, availability,
price status, source, and a content fingerprint. Missing price is explicit and
causes token history—not an invented monetary value—to drive cost ordering.

Classification order is declared task metadata, valid persisted classification,
then deterministic inference. LOW-confidence inference returns
`CLASSIFICATION_REQUIRED`. Complexity and risk establish floors; capabilities
can raise but never reduce them. Metrics reorder candidates only within an
eligible floor.

## Per-activity proposal and approval

```bash
agent-kit continue T33 --harness opencode --provider openai --propose --json
agent-kit continue --approve <proposal-id>
agent-kit continue --approve <proposal-id> \
  --model developer=<model-id> \
  --model reviewer=<model-id>
agent-kit continue T33 --harness opencode --provider openai --yes
```

The proposal lists every discovered provider model. Models below the role floor
or without an executable route are shown disabled with a reason. Stronger
models may be selected without reclassification. The Orchestrator is locked;
change it persistently with `--orchestrator-model` during init/reinstall/catalog
refresh.

A proposal is bound to task, adjacent state, and catalog hashes. Changes make it
stale. Non-interactive execution without `--propose`, `--approve`, or explicit
`--yes` returns `INTERACTION_REQUIRED`. Provider names are strict; only `auto`
may cross provider boundaries. The approved plan contains the allowed fallback
order, so any unlisted fallback requires a new approval.

## Context and receipts

Each plan role contains a `ContextCapsule` with only objective, acceptance,
decisions, paths/diff, dependencies, known failures, and gates. Adapters load
that capsule, project rules, and relevant protocol sections instead of replaying
the full conversation or all skills.

```bash
agent-kit dispatch record \
  --plan <plan-id> \
  --role developer \
  --result PASS \
  --effective-model <model-id> \
  --input-tokens 1200 \
  --output-tokens 300 \
  --cache-tokens 800 \
  --gate "unit tests PASS"

agent-kit usage report --json
```

Receipts contain fact-only execution metadata. An unapproved effective model is
rejected as `MODEL_MISMATCH`. Prompts, transcripts, sessions, reasoning, and
credentials are not accepted or stored.

On a verified quota, rate-limit, or unavailable-model failure, advance the
plan's circuit breaker without inventing a route:

```bash
agent-kit dispatch next-fallback \
  --plan <plan-id> \
  --role developer \
  --failed-model <model-id> \
  --json
```

The command returns only the next approved route. Exhaustion returns
`CIRCUIT_OPEN` and requires a new proposal.

## Harness capability notes

- OpenCode uses project agents and bounded permissions; its model-specific
  routes dispatch the corresponding generated agent. The framework deliberately
  does not set `steps`, because that would terminate long orchestrations instead
  of letting approved activity budgets and circuit breakers govern cost.
- Codex keeps the root session unchanged and supplies explicit model and
  `model_reasoning_effort` to subagents.
- Copilot uses `.github/agents`, `.github/instructions`, and `.github/prompts`;
  effort remains a plan/receipt contract because its portable custom-agent
  frontmatter has no shared reasoning-effort field.
- Claude Code uses `.claude/agents` and `.claude/commands`, with model, effort,
  tools, and bounded worker turns; the Orchestrator has no fixed turn cap, and
  per-invocation model selection follows the approved plan.

Adapter formats track the official references: [OpenCode agents](https://opencode.ai/docs/agents),
[Codex subagents](https://developers.openai.com/codex/multi-agent),
[Copilot custom agents](https://docs.github.com/en/copilot/reference/custom-agents-configuration),
and [Claude Code subagents](https://code.claude.com/docs/en/sub-agents).
