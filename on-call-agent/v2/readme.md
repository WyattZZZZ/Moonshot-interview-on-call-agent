# On-Call Agent v2

v2 是语义检索层。它用本地 embedding 和 Chroma 替换了早期稀疏语义实验。

## 系统职责

v2 负责：

- 按标题结构切分 HTML
- 使用 `BAAI/bge-small-zh-v1.5` 生成 query 和 chunk embedding
- 将向量数据存入 `database/chroma/`
- 为 v3 融合检索提供语义分数

v2 仍然会把文档元数据和清洗正文写入 SQLite，因此 v1 和 v3 可以共享同一个文档目录。

## 模型

默认 embedding 模型：

```text
BAAI/bge-small-zh-v1.5
```

query 文本使用以下指令前缀：

```text
为这个句子生成表示以用于检索相关文章：
```

chunk 文本由标题路径和 chunk 正文拼接后送入模型。embedding 模型会在进程内缓存，并用锁保护初始化流程，避免并发 v3 请求重复加载模型。

环境变量：

```bash
HF_ENDPOINT=https://huggingface.co
HF_HUB_DISABLE_XET=1
ON_CALL_AGENT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ON_CALL_AGENT_CHROMA_DIR=./database/chroma
```

## 文档切块

`v2/chunker.py` 会按 `h1` 到 `h6` 拆分 HTML。

规则：

- 每个标题会开启一个新 chunk
- 每个 chunk 会保存当前标题路径
- 少于 10 个字符的 chunk 会被丢弃
- 没有标题的文档会在正文足够长时退化为一个纯文本 chunk
- 不生成额外的引言 chunk

## 存储

- SQLite `documents`：规范文档元数据、清洗正文和原始 HTML。
- Chroma collection：chunk 文本、chunk 元数据和 embedding 向量。
- 旧的 SQLite 向量字段会在 v2 文档写入时清空，当前不再用于语义检索。

## 启动

```bash
cd on-call-agent
uv sync
uv run python v2/server.py \
  --host 127.0.0.1 \
  --port 8000 \
  --import-demo \
  --demo-dir ../coding-exam/question-1/data
```

示例数据导入是幂等的。使用 `--refresh-demo` 可以覆盖已有示例行，并重新生成 Chroma chunks。

## API

创建文档：

```bash
curl -sS -X POST http://127.0.0.1:8000/v2/documents \
  -H 'Content-Type: application/json' \
  -d '{"id":"example-001","title":"Example SOP","html":"<h1>Example SOP</h1><p>服务异常处理。</p>"}'
```

读取文档：

```bash
curl -sS http://127.0.0.1:8000/v2/documents/sop-001
```

删除文档：

```bash
curl -sS -X DELETE http://127.0.0.1:8000/v2/documents/example-001
```

搜索：

```bash
curl -sS 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
curl -sS 'http://127.0.0.1:8000/v2/search?q=黑客攻击'
curl -sS 'http://127.0.0.1:8000/v2/search?q=推荐质量下降'
```

搜索响应包含文档 id、标题、摘要、归一化分数、命中的 chunk id、命中标题、标题路径和 chunk 数量。

## 与 v3 的集成

v3 当前在进程内导入 `v2/search.py` 并调用 `search_documents_semantic`，不会通过 HTTP 调用 v2。模块加载器会保留有效缓存；只有上一次局部导入后缺少预期函数时，才会重新加载模块。

## 验证

```bash
uv run python -m py_compile database/db.py database/chroma_store.py v2/chunker.py v2/semantic.py v2/search.py v2/server.py
uv run python v2/server.py --host 127.0.0.1 --port 8000 --import-demo
curl -sS 'http://127.0.0.1:8000/v2/search?q=服务器挂了'
```
