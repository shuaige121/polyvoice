# Polyvoice Vocabulary Curation Contract

Inputs:

- `vocab/candidates.jsonl`: generated candidate terms with score, count, language, source sessions, and redacted snippets.
- `vocab/manual.jsonl`: optional user-maintained entries. These always win.

Output:

- `vocab/master.jsonl`, one JSON object per line.
- Every row must include `schema_version: 1`.

Keep terms that improve speech recognition for this user:

- Project names, library names, framework names, product names, command names, acronyms, proper nouns, technical terms, Chinese domain phrases, and mixed Chinese-English terms.
- Terms from IME imports unless they are clearly malformed or secret-like.
- Aliases that the user may say aloud, for example lower-case forms for acronyms or alternate spellings.

Drop terms that are unsafe or low value:

- API tokens, JWTs, hashes, UUIDs, URLs, emails, IP addresses, file paths, environment variable names, base64-looking blobs, and other identifiers that look secret or machine-generated.
- Common words, punctuation fragments, stop words, single Chinese characters, pure numbers, raw code syntax, JSON keys, shell output, and pasted log noise.
- Very short English fragments under 2 characters or very long terms over 80 characters.

Category rules:

- `library`: CamelCase or recognizable package/framework/product names.
- `acronym`: all-caps or short acronym-like names.
- `domain`: Chinese terms, mixed domain terms, product concepts, and normal technical vocabulary.
- `command`: user-spoken command names.
- `project`: repository or project codenames.
- `person`: person names.
- `id`: non-secret identifiers that are useful to dictate.

Merge rules:

- Normalize English keys case-insensitively; keep Chinese exact.
- Accumulate `count`, `sources`, `aliases`, `first_seen`, and `last_seen`.
- Preserve manual phrase, lang, category, aliases, and notes when a manual entry conflicts with a generated entry.
- Keep snippets short and redacted; do not add raw secret-bearing context.

Recommended row shape:

```json
{"schema_version":1,"phrase":"CosyVoice3","lang":"en","category":"library","aliases":["cosyvoice3"],"first_seen":"2026-04-14T12:00:00","last_seen":"2026-04-14T12:00:00","count":3,"sources":["scan-session"],"weight":1.477}
```
