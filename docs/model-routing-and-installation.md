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

The lock records normalized `ModelDescriptor` facts: provider/model ID, display
name, input/output/reasoning price where available, cost tier, coding/review/
reasoning/tool capability, context/output limits, availability and metadata
source. Unknown models remain valid catalog entries; project-owned
`[model_metadata]` overrides can add facts without modifying routing code.

The default policy is intentionally asymmetric:

- Orchestrator: `CAPABILITY_FIRST`, prioritizing reasoning and tool capability,
  then cost among equivalent candidates.
- Developer, Planner, Reviewer, QA, Explorer, Researcher, Verifier and
  mechanical roles: `COST_FIRST`. Capability, tool support and context are
  constraints; expected execution cost is the optimization target.

When input/output prices are known, selection compares estimated execution cost.
Otherwise it uses `ECONOMY`, `STANDARD`, then `PREMIUM`. No production routing
rule depends on a model name.

Classification order is declared task metadata, valid persisted classification,
then deterministic inference. LOW-confidence inference returns
`CLASSIFICATION_REQUIRED`. Complexity and risk establish gates and required
capabilities; they do not automatically select a premium worker.

## OpenCode with GitHub Copilot provider

For corporate environments where OpenCode is the allowed harness and GitHub
Copilot is the only authorized model provider, configure the project once:

```bash
opencode
```

Inside OpenCode, run `/connect`, select GitHub Copilot, and complete the
OAuth/device login. Authentication stays with OpenCode; the framework never
reads, persists, or logs Copilot tokens. Then check `/models` to confirm the
entitled models.

Back in the terminal:

```bash
agent-kit init \
  --profile flutter \
  --harness opencode \
  --provider copilot
```

This persists `control harness = opencode`, `default provider = copilot`,
`allowed provider = copilot`, and `strict provider = true` in
`.agent-framework.toml`:

```toml
[provider]
default = "copilot"
allowed = ["copilot"]
strict = true
```

Re-running `agent-kit init --force` without `--provider` reuses the persisted
policy, like other persisted settings. Copilot models are discovered
dynamically through the officially supported `opencode models --verbose`
interface (`github-copilot` is normalized to the framework provider
`copilot`); nothing is hardcoded because entitlements vary by company,
account, plan, policy, and region.

Diagnose and verify:

```bash
agent-kit env --check
agent-kit doctor
agent-kit catalog show
agent-kit route simulate T33 \
  --workflow continue \
  --harness opencode \
  --provider copilot \
  --json
```

In strict mode there is no silent fallback to another provider: quota,
rate-limit, or unavailable-model failures advance only within previously
approved Copilot fallbacks, otherwise `CIRCUIT_OPEN`. A missing or
unauthorized Copilot surfaces as `COPILOT_PROVIDER_UNAVAILABLE` in `doctor`
and `ORCHESTRATOR_UNAVAILABLE` when no entitled model meets the
control-plane floor. Omitting `--provider` resolves to the project default
(`copilot`), never to cross-provider `auto`.

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

Workers receive a low/very-low context and output budget by default. The
Orchestrator has high context/reasoning and medium output budgets. Capsules pass
task, acceptance, owned paths, relevant decisions, gates and artifact references
only. Large command output is reduced to command, exit context, relevant error
lines and a full-log reference.

Escalation is progressive (`ECONOMY -> STANDARD -> PREMIUM`) and centrally
validated. It requires evidence such as missing capability/tool support,
insufficient context, an invalid patch, repeated implementation failure or review
convergence failure. One repair on the same model and at most two tier
escalations are allowed; exhausted work uses the existing human escalation path.

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

## Decision Plane: bounded shadow observation

The optional Decision Plane is disabled by default and accepts only `disabled` or
`shadow` mode. It observes the deterministic workflow after task/state
reconciliation and before the existing proposal is built; its recommendation
never changes state, gates, convergence, roles, proposal identity, approval,
fallback order, model selection, harness commands, or dispatch. OpenCode, Codex,
Copilot, and Claude Code use the same core contracts; adapters do not implement
decision policy.

### Configuration defaults and bounds

The manifest contract is:

```toml
[decision]
enabled = false
mode = "shadow"
providers = ["deterministic-safe"]
audit_path = ".agent-managed/runtime/decision-audit.jsonl"

[decision.policy]
minimum_confidence = 0.70
reasoning_probability = 0.70
review_probability = 0.60
qa_probability = 0.60
escalation_probability = 0.70

[decision.context]
max_questions = 12
max_metadata_facts = 32
max_text_chars = 2000
max_bytes = 16384
```

`audit_path` must be a non-empty relative project path and cannot contain `..`.
All context bounds are positive integers, cannot exceed the values above, and
`max_questions` cannot be below the 12-question schema. Policy thresholds are
finite numbers in the inclusive range `0..1`. Provider names must be unique and
are limited to `deterministic-safe`, `mock`, and `jev`.

The bounded context contains an objective, declared requirements, and compact
scalar facts from task, route, and current state. It excludes `prompt`,
`transcript`, `reasoning`, `session`, and similar raw conversation fields.
Strings are capped, metadata is capped, and canonical serialized context is
bounded to 16 KiB; truncation is deterministic and unsafe values are rejected.

Audit is fact-only. Pre records require `feature`, `task`, `provider`, `profile`,
`confidence`, `policyRecommendation`, `authoritativeDecision`, `usage`, and
`mismatch`. Post records require `correlationId`, `eventualResult`,
`comparison`, `usage`, `model`, and `orphanedPreObservation`. Records are
bounded to 64 fields/items and 16 KiB. They exclude prompts, payloads,
requests/responses, transcripts, reasoning, sessions, credentials, secrets,
full diffs, and raw logs. Runtime files are
`.agent-managed/runtime/decision-observations/<correlation-id>.json` and
`.agent-managed/runtime/decision-audit.jsonl`; they are not canonical state.

### Schema, profile, and policy are separate

The **schema** is the vendor-neutral question contract: choice, score, and
probability questions with validation and canonical serialization. The
**profile** is the normalized `TaskDecisionProfile`: typed answers carrying
status (`ANSWERED`, `UNKNOWN`, or `UNSUPPORTED`), provider ID, value, and
confidence. Provider-specific fields and payloads do not survive normalization.
The **policy** is a pure evaluator over that profile plus deterministic facts;
it returns an immutable recommendation with execution tier, model-class floor,
review/QA/escalation flags, and reason codes. Policy does not select a provider
or model and performs no I/O.

Required profile answers below `minimum_confidence`, missing answers, or
unsupported answers are conservative evidence: policy recommends Orchestrator
escalation and does not weaken review, QA, or execution floors.

### Tiers, precedence, and existing routing

Execution tiers map exactly to existing portable model classes:

| Decision tier | Existing model class |
| --- | --- |
| `ECONOMY` | `cost-efficient-coding` |
| `BALANCED` | `balanced-coding` |
| `REASONING` | `strong-coding` |
| `FRONTIER` | `strongest-appropriate` |

Precedence is deterministic and monotonic: explicit task metadata and
deterministic risk, required review/QA, gate failures, and convergence stops
establish floors first; semantic probability/confidence may recommend stronger
handling; semantic evidence can never lower a deterministic floor. Complexity
and risk select gates and safety floors, not a premium worker model. The
existing `ModelRouter` then applies capability constraints and its established
strategy (Orchestrator `CAPABILITY_FIRST`; other roles `COST_FIRST`) against the
current catalog.

### Provider contract, chain, and Jev boundary

Every provider implements `capabilities()` and `evaluate(request)`. Capabilities
declare a stable provider ID, supported decision kinds, status
(`AVAILABLE`, `UNAVAILABLE`, or `UNSUPPORTED`), maximum request bytes, and
optional usage/model reporting. The chain tries configured providers once, in
order, validates each normalized result, records compact failure categories
(`unavailable`, `unsupported`, `timeout`, `error`, `invalid`, or `oversized`),
and falls through. A deterministic-safe provider is always appended as the
terminal provider; it copies only authoritative known task classifications and
returns explicit unknown semantic answers.

`jev` is an explicit, shadow-only HTTP provider. It is disabled by default;
the deterministic provider remains the terminal fallback. To opt in manually,
keep the Decision Plane in shadow mode and configure:

```toml
[decision]
enabled = true
mode = "shadow"
providers = ["jev", "deterministic-safe"]

[decision.jev]
endpoint = "https://api.typesafe.ai/v1/systemone"
model = "jev-latest"
timeout = 10.0
```

Set `TYPESAFE_API_KEY` in the process environment. The key is environment-only:
it is never placed in the manifest, source, payload, logs, receipts, or audit
records. The endpoint is validated before reading the API key or making a
network call: it must use HTTPS, include a host, and contain no userinfo,
query, or fragment. The configured HTTPS proxy or test origin is the transport
trust boundary; redirects are not followed.

The official request uses bounded canonical state and canonical Choice, Score,
and Noul question shapes. Responses normalize into the central profile. Score
validates the fractional expected index, probabilities, and legend, then rounds
to the nearest central-scale position; an exact `.5` rounds toward the higher
(more conservative) position and the central result is an integer scale value.
Noul preserves the central `noul` probability and derives confidence exactly as
`abs(2 * noul - 1)`. Provider output is non-authoritative: Jev cannot alter
routing, approval, state, gates, fallback order, or model selection.

The adapter makes exactly one attempt and performs zero retries. HTTP 401, 429,
and 529 map to `unavailable`; 422 maps to `invalid`; timeouts map to `timeout`;
and other transport or response failures map to `error`. Every failure falls
through to `deterministic-safe`. Audit output is fact-only and excludes
credentials, `Authorization`, request/response payloads and bodies, raw
probabilities, legends, and remote error text. Only bounded safe metadata such
as model, token counts, and latency may be recorded.

After upgrading a consumer with `agent-kit sync`, the managed runtime and
documentation receive this Jev implementation. Sync does not modify the
project-owned `.agent-framework.toml`; operators must manually opt in through
the configuration above and provide `TYPESAFE_API_KEY` in the environment.

### Filling a legacy manifest: `sync --update-manifest`

A project whose manifest predates the Decision Plane can adopt the canonical
structure without hand-editing TOML:

```bash
agent-kit sync --update-manifest
```

The flag is additive and section-aware. For `[decision]`, `[decision.jev]`,
`[decision.policy]`, and `[decision.context]` it fills only what is missing, from
`templates/agent-framework.toml`:

- Every existing value, comment, key order, unrelated section, and the file's
  newline style (LF or CRLF) is preserved byte for byte.
- A whole missing table is appended in canonical order; a partial table receives
  only its missing keys.
- It never enables Jev. A missing `[decision] enabled` is always written as
  `false`, an existing `enabled = true` is left untouched, and no credential,
  key, token, or `.env` value is read, generated, or written anywhere.
- Before any managed write it rejects a duplicate `[decision*]` header, a
  duplicate key inside a managed section, a non-canonical key inside one, a
  value whose type differs from the template's, a value used where a table is
  required, and malformed TOML. The whole sync aborts and leaves the manifest and
  managed assets untouched.
- On change it writes the previous bytes once to
  `.agent-managed/backups/agent-framework.toml.before-update-manifest`, writes
  atomically, reparses and validates the complete result (all canonical keys and
  tables present exactly once), then prints `MANIFEST: updated`. An unchanged
  manifest prints `MANIFEST: unchanged`. Sync continues in both cases.

Because the fill is inert, activation is still a deliberate manual step:

```toml
[decision]
enabled = true
providers = ["jev", "deterministic-safe"]
```

then export `TYPESAFE_API_KEY` in the environment. Nothing in the sync path
reads it for you.

A future LLM adapter must reuse the central schema/profile/provider contracts,
the existing catalog and `ModelRouter`, and the existing proposal/approval
flow. It must not hardcode model IDs, create a second registry, bypass
approval, or invent a parallel provider-discovery path. Paid/model-backed
pre-proposal calls require a separately approved cost and security contract.
