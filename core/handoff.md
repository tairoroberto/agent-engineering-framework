# Handoff

```text
GOAL: <outcome>
STATE: <implemented|blocked|reviewing>
FILES: <paths>
DECISIONS: <confirmed decisions>
VERIFY: <command: result>
RISKS: <risk|none>
OPEN: <next action|none>
```

For delegated work, add only needed fields: `TASK`, `REQS`, `ADS`, `BASE`, `HEAD`, `GATE`, `COMMIT`. Reviewer evidence uses `REQ`, `FILE:LINE`, `ISSUE`, `EXPECTED`; verifier evidence uses `SCENARIO`, `RESULT`, `EVIDENCE`. Escalation states attempt count, blocker facts, options.

No chain-of-thought, raw transcripts, credentials, or boilerplate. Receiver rechecks current source and project rules.
