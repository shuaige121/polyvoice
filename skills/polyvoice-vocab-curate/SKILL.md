# polyvoice vocab curate

Use this skill when curating Polyvoice vocabulary candidates.

The source of truth is the repository contract at `vocab/curation_prompt.md`.

Workflow:

1. Read `vocab/curation_prompt.md`.
2. Read `vocab/candidates.jsonl`.
3. Apply the contract exactly: drop noise and secrets, keep real vocabulary, categorize terms, and merge aliases.
4. Preserve or update `vocab/master.jsonl` with JSONL entries that include `schema_version: 1`.
5. Treat `vocab/manual.jsonl` as authoritative. Manual entries always win over generated decisions.

Do not call an external LLM API from this skill. The contract format is intentionally portable: any human, local model, or agent that can read `curation_prompt.md` and `candidates.jsonl` can perform the curation.
