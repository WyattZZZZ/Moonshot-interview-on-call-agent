# on-call-agent v1

v1 is a lightweight HTTP API built with Python standard library modules and SQLite FTS5. It stores shared data in `on-call-agent/database` and does not modify the original `coding-exam/question-1/data` files.

## Run

Install and sync dependencies once from `on-call-agent/`:

```bash
cd on-call-agent
uv sync
```

```bash
uv run python v1/server.py --host 127.0.0.1 --port 8000 --import-demo
```

`--import-demo` is idempotent: existing demo documents are skipped so server restarts do not overwrite uploaded content or future v2 fields. Use `--refresh-demo` together with `--import-demo` only when you intentionally want to overwrite the demo SOP rows.

The default database path is:

```text
database/on_call_agent.sqlite3
```

Override it with either `--db /path/to/file.sqlite3` or `ON_CALL_AGENT_DB=/path/to/file.sqlite3`.

## API

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Create or replace a document:

```bash
curl -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{"id":"sop-001","html":"<html><head><title>Example</title></head><body>OOM recovery</body></html>"}'
```

Upload guardrails:

- Duplicate IDs return `409` unless the JSON body includes `"replace": true`.
- IDs must be 1-120 characters and use letters, numbers, `.`, `_`, or `-`.
- JSON request bodies are capped at 2 MiB.
- HTML content is capped at 1,000,000 characters.

Get a document:

```bash
curl http://127.0.0.1:8000/v1/documents/sop-001
```

Delete a document:

```bash
curl -X DELETE http://127.0.0.1:8000/v1/documents/sop-001
```

Search:

```bash
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v1/search?q=故障'
curl 'http://127.0.0.1:8000/v1/search?q=CDN'
curl 'http://127.0.0.1:8000/v1/search?q=%26'
```

## Notes

- `documents` includes v2-compatible nullable `semantic_profile` and `embedding` fields.
- `embeddings` exists for future vector records and allows nullable vector values.
- `script` and `style` content is removed before indexing, so words that only appear in scripts are not searchable.
- Search uses jieba to tokenize Chinese text before writing to SQLite FTS5, then ranks matches with `bm25`.
- Queries that cannot be represented as an FTS query, such as `&`, fall back to a literal `LIKE` search against title and cleaned text with a low fallback score.
