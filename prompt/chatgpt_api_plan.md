Moonshot On-Call Assistant

API 接口文档 + 开发流程 TODO

⸻

1. 项目结构

/v1 → Keyword Search
/v2 → Semantic Search
/v3 → Tool-Using Agent

三个版本共享：

* SQLite
* 文档存储
* HTML 解析
* 前端基础结构
* .env

⸻

2. v1 API

v1：Keyword Search Engine

技术实现：

SQLite FTS5 + BM25

⸻

POST /v1/documents

新增 SOP 文档。

Request

{
  "id": "sop-001",
  "html": "<html>...</html>"
}

⸻

Response

{
  "id": "sop-001",
  "title": "后端服务 On-Call SOP"
}

⸻

GET /v1/documents/{id}

获取文档。

⸻

Response

{
  "id": "sop-001",
  "title": "后端服务 On-Call SOP",
  "clean_text": "..."
}

⸻

DELETE /v1/documents/{id}

删除文档。

⸻

Response

{
  "success": true
}

⸻

GET /v1/search?q={query}

关键词搜索。

实现：

FTS5 MATCH + bm25()

⸻

Response

{
  "query": "OOM",
  "results": [
    {
      "id": "sop-001",
      "title": "后端服务 On-Call SOP",
      "snippet": "...OOM 排查...",
      "score": 0.91
    }
  ]
}

⸻

GET /v1

返回搜索页面。

页面结构：

搜索框
↓
结果列表

⸻

3. v2 API

v2：Hybrid Semantic Search

技术实现：

SQLite + embedding + hybrid reranking

注意：

v2 不是传统 chunk-based RAG。

v2 仅进行：

document-level semantic retrieval

⸻

POST /v2/documents

新增文档。

额外执行：

* semantic_profile 生成
* embedding 生成

⸻

Request

{
  "id": "sop-001",
  "html": "<html>...</html>"
}

⸻

Response

{
  "id": "sop-001",
  "semantic_profile": "OOM、服务超时、故障分级、降级策略"
}

⸻

GET /v2/documents/{id}

获取文档。

返回：

* clean_text
* semantic_profile

⸻

Response

{
  "id": "sop-001",
  "title": "后端服务 On-Call SOP",
  "semantic_profile": "OOM、服务超时、故障分级"
}

⸻

DELETE /v2/documents/{id}

删除文档。

同步删除：

* embedding
* semantic_profile

⸻

Response

{
  "success": true
}

⸻

GET /v2/search?q={query}

语义搜索。

流程：

keyword search
+
semantic similarity
+
hybrid reranking

⸻

Response

{
  "query": "服务器挂了",
  "results": [
    {
      "id": "sop-001",
      "title": "后端服务 On-Call SOP",
      "snippet": "...服务超时...",
      "score": 0.87
    },
    {
      "id": "sop-004",
      "title": "SRE On-Call SOP",
      "snippet": "...故障响应...",
      "score": 0.82
    }
  ]
}

⸻

GET /v2

返回语义搜索页面。

与 v1 共用页面。

页面结构：

搜索框
↓
Tab
- Keyword Search
- Semantic Search
↓
结果列表

⸻

4. v3 API

v3：Tool-Using Agent

核心原则：

Agent only has one tool:
readFile(fname)

符合题目要求。

⸻

POST /v3/chat

Agent 对话接口。

⸻

Request

{
  "message": "数据库主从延迟超过30秒怎么处理？",
  "history": []
}

⸻

Workflow

用户问题
 ↓
semantic search routing
 ↓
候选文件选择
 ↓
readFile(fname)
 ↓
LLM answer generation

⸻

Response

{
  "answer": "建议先检查复制线程状态和 binlog 堆积情况...",
  "steps": [
    {
      "type": "search",
      "query": "数据库主从延迟超过30秒怎么处理？",
      "candidates": [
        "sop-002.html"
      ]
    },
    {
      "type": "tool_call",
      "tool": "readFile",
      "args": {
        "fname": "sop-002.html"
      }
    },
    {
      "type": "tool_result",
      "fname": "sop-002.html",
      "result_preview": "数据库 DBA On-Call SOP..."
    }
  ]
}

⸻

GET /v3

返回聊天页面。

页面结构：

聊天记录
↓
用户输入框
↓
Tool Call 展示
↓
Tool Result 展示

⸻

5. SQLite 数据结构

⸻

documents

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    title TEXT,
    html TEXT,
    clean_text TEXT,
    semantic_profile TEXT,
    path TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

⸻

documents_fts

CREATE VIRTUAL TABLE documents_fts USING fts5(
    id,
    title,
    clean_text
);

⸻

embeddings

CREATE TABLE embeddings (
    doc_id TEXT PRIMARY KEY,
    vector BLOB
);

⸻

6. .env

MOONSHOT_API_KEY=
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
CHAT_MODEL=kimi-k2
EMBEDDING_MODEL=
DATABASE_URL=sqlite:///./oncall.db
DATA_DIR=./data

⸻

7. 开发流程 TODO

⸻

Phase 1 TODO

数据层

* 建立 SQLite 数据库
* 建立 documents 表
* 建立 FTS5 表

⸻

HTML 清洗

* BeautifulSoup 解析 HTML
* 删除 script 标签
* 删除 style 标签
* 提取 title
* 提取 clean_text

⸻

API

* POST /v1/documents
* GET /v1/documents/{id}
* DELETE /v1/documents/{id}
* GET /v1/search

⸻

搜索

* FTS5 MATCH
* bm25() 排序
* snippet 截取

⸻

前端

* 搜索框
* 搜索结果列表
* query 参数同步

⸻

验证

* OOM 返回 sop-001
* CDN 返回 sop-003/sop-010
* replication 返回空
* 特殊字符 & 正常工作

⸻

Phase 2 TODO

Semantic Search

* semantic_profile 生成
* embedding 生成
* embedding 存储

⸻

Hybrid Search

* cosine similarity
* keyword score normalization
* semantic score normalization
* hybrid reranking

⸻

API

* POST /v2/documents
* GET /v2/search
* embedding 删除同步

⸻

前端

* v1/v2 tab 切换
* semantic score 展示
* 搜索模式切换

⸻

验证

* 服务器挂了 → sop-001/sop-004
* 黑客攻击 → sop-005
* 推荐质量下降 → sop-008

⸻

Phase 3 TODO

Agent

* history 管理
* tool schema 定义
* readFile 工具实现
* agent状态回滚

⸻

Workflow

* semantic search routing
* candidate selection
* tool call execution
* final answer generation

⸻

Frontend

* Chat UI
* Thinking 展示
* Tool Call 展示
* Tool Result 展示
* 对话历史

⸻

验证

* 数据库主从延迟 → sop-002
* 服务 OOM → sop-001
* P0 故障流程 → 多文件综合
* 入侵检测 → sop-005
* 推荐质量下降 → sop-008

⸻

8. 最终交付

最终提交：

* 源码
* README
* requirements.txt
* .env.example
* SQLite 数据库
* data/ 示例数据
* API 文档
* 前端页面

⸻

9. 项目最终定位

最终系统定位：

Hybrid Semantic Search + Tool-Using Agent

不是：

Traditional Chunk-Based RAG

核心设计原则：

* document-level retrieval
* explicit file reading
* lightweight architecture
* explainable workflow
* hybrid semantic ranking