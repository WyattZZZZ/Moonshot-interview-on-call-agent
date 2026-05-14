# On-Call Agent v1

v1 是关键词检索基线版本。它使用 Python 标准库 HTTP 服务、SQLite、SQLite FTS5 和 jieba 分词。

## 系统职责

v1 负责：

- 文档创建、读取、删除 API
- 将清洗后的 HTML 文本存入 SQLite
- 维护 FTS5 关键词索引
- 为 v3 融合检索提供关键词分数

SQLite schema 会被后续版本复用。`documents` 表中保留了可为空的语义字段，方便 v2 写入向量相关元数据，而不需要重置迁移。

## 存储

默认数据库：

```text
database/on_call_agent.sqlite3
```

主要数据表：

- `documents`：文档 id、标题、清洗后的正文、原始 HTML，以及可选的语义字段。
- `documents_fts`：基于标题和清洗正文的 FTS5 索引。
- `embeddings`：为向量记录保留的兼容表；当前 v2 的实际语义检索使用 Chroma。

服务重启不会清空数据库。除非传入 `--refresh-demo`，示例数据导入是幂等的。

## 启动

```bash
cd on-call-agent
uv sync
uv run python v1/server.py --host 127.0.0.1 --port 8000 --import-demo --demo-dir ../coding-exam/question-1/data
```

覆盖数据库路径：

```bash
ON_CALL_AGENT_DB=/tmp/on_call_agent.sqlite3 uv run python v1/server.py
```

## API

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

创建文档：

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{"id":"sop-001","html":"<html><head><title>Example</title></head><body>OOM recovery</body></html>"}'
```

重复 id 默认返回 `409`。如果请求体包含 `"replace": true`，则覆盖已有文档。

读取文档：

```bash
curl http://127.0.0.1:8000/v1/documents/sop-001
```

删除文档：

```bash
curl -X DELETE http://127.0.0.1:8000/v1/documents/sop-001
```

搜索：

```bash
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
curl 'http://127.0.0.1:8000/v1/search?q=故障'
```

## 保护规则

- 请求 JSON body 最大为 2 MiB
- HTML 内容最大为 1,000,000 字符
- 文档 id 只允许字母、数字、`.`、`_`、`-`
- 建索引前会移除 `script` 和 `style` 内容
- 非法 FTS 查询会回退到字面量 `LIKE` 搜索，并给出较低的兜底分数

## 验证

```bash
uv run python -m py_compile database/db.py v1/server.py v1/search.py
uv run python v1/server.py --host 127.0.0.1 --port 8000 --import-demo
curl 'http://127.0.0.1:8000/v1/search?q=OOM'
```
