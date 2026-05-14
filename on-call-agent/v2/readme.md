# On-Call Agent v2

v2 adds deterministic local semantic search on top of the v1 SQLite FTS5 keyword index. It does not call any external LLM or embedding API.

## Run

```bash
cd on-call-agent
uv run python v2/server.py --host 127.0.0.1 --port 8000 --import-demo
```

Demo import is idempotent: existing `sop-*.html` documents are skipped by default. Use `--refresh-demo` to overwrite and regenerate their semantic profile and embedding.

## API

Create or replace a document:

```bash
curl -sS -X POST http://127.0.0.1:8000/v2/documents \
  -H 'Content-Type: application/json' \
  -d '{"id":"example-001","title":"Example SOP","html":"<h1>Example SOP</h1><p>服务异常处理。</p>"}'
```

Duplicate ids return `409` unless `replace:true` is present. Invalid ids, empty HTML, invalid JSON, and oversized bodies return clear JSON errors.

Get a document:

```bash
curl -sS http://127.0.0.1:8000/v2/documents/sop-001
```

Delete a document:

```bash
curl -sS -X DELETE http://127.0.0.1:8000/v2/documents/example-001
```

Search:

```bash
curl -sS 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
```

Responses include:

- `query`
- `results[].id`
- `results[].title`
- `results[].snippet`
- `results[].score`
- `results[].keyword_score`
- `results[].semantic_score`
- `results[].semantic_profile`

## Local Semantic Implementation

`v2/semantic.py` builds a deterministic `semantic_profile` and sparse JSON `embedding` from jieba search tokens. Title tokens receive extra weight, high-frequency body tokens are log-scaled, and a small domain synonym map expands common on-call phrases such as `服务器挂了`, `黑客攻击`, and `推荐质量下降`.

The vector is stored in both `documents.embedding` and the shared `embeddings` table with model name `local-jieba-keyword-sparse-v1`. This keeps the API boundary ready for a future real embedding provider without changing v2 request handling.

Hybrid reranking combines normalized FTS `bm25` score and semantic cosine similarity:

```text
score = 0.58 * keyword_score + 0.42 * semantic_score
```

## Verification

```bash
cd on-call-agent
uv run python -m py_compile database/db.py v2/semantic.py v2/search.py v2/server.py
uv run python v2/server.py --host 127.0.0.1 --port 8000 --import-demo

curl -sS 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -sS 'http://127.0.0.1:8000/v2/search?q=黑客攻击'
curl -sS 'http://127.0.0.1:8000/v2/search?q=机器学习模型出问题/推荐质量下降'
```
