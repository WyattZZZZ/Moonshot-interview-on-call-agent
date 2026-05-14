# Moonshot On-Call Agent

这是一个面向 `coding-exam/question-1/data` 中 SOP 文档的分版本检索与问答示例项目。

## 总体架构

项目包含三个后端版本和一个静态 Web UI：

- `v1`：基于 SQLite FTS5 的关键词检索。文档入库前会清洗 HTML，并使用 jieba 分词后建立索引。
- `v2`：基于本地向量模型 `BAAI/bge-small-zh-v1.5` 的语义检索。HTML 会按标题切块，向量和元数据存入 Chroma。
- `v3`：使用 Moonshot/Kimi 的工具调用 Agent。它会融合 v1 关键词分数和 v2 语义分数，只把高置信候选文档暴露给模型，并且模型只能调用 `readFile(fname)`。
- `webui`：静态 HTML/CSS/JS 前端，提供 v1/v2 搜索页签和 v3 聊天页签。

共享状态位于 `database/`：

- `database/on_call_agent.sqlite3`：文档元数据、清洗后的正文，以及 v1 的 FTS 索引。
- `database/chroma/`：v2 的文档切块向量和元数据。

v3 的文件读取工具被限制在 `../coding-exam/question-1/data`。模型不会看到本地路径，只能请求候选文档文件名，harness 会把文件名拼接到固定数据目录后再读取。

## 一键启动

在 `on-call-agent/` 目录中运行：

```bash
uv sync
./run_all.sh
```

Windows 下运行：

```bat
run_all.bat
```

启动脚本会拉起所有本地服务，并打开：

```text
http://127.0.0.1:4173/#v1
```

默认端口：

- API 网关：`8000`
- v1 后端：`8001`
- v2 后端：`8002`
- v3 HTTP 后端：`8003`
- v3 WebSocket 流：`8004`
- Web UI：`4173`

启动脚本会在启动前检测端口占用，并在启动后轮询 v1、v2、v3、v3 WebSocket、gateway 和 Web UI 的健康状态。设置 `NO_OPEN=1` 可以只启动服务，不自动打开浏览器；设置 `STARTUP_TIMEOUT=秒数` 可以调整等待服务 ready 的最长时间。

## API 网关

`dev_gateway.py` 提供一个面向浏览器的统一 API base：

```text
/v1 -> http://127.0.0.1:8001
/v2 -> http://127.0.0.1:8002
/v3 -> http://127.0.0.1:8003
```

网关会移除上游服务返回的 CORS 头，并只写入一组 CORS 头，避免浏览器看到重复的 `Access-Control-Allow-Origin`。

## v3 聊天流程

同步接口仍然可用：

```bash
curl -sS http://127.0.0.1:8000/v3/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"服务 OOM 了怎么办？","history":[],"weights":{"keyword":0.5,"semantic":0.5}}'
```

Web UI 使用流式路径：

1. `POST /v3/chat/session` 创建一个短生命周期会话，返回 `session_id` 和 `ws_url`。
2. 浏览器连接 `ws_url`。
3. 浏览器发送 `{"session_id":"..."}`。
4. 服务端持续发送 JSON 事件：`status`、`retrieval`、`assistant`、`tool`、`final`、`error`。

每个 `tool` 事件都会在工具调用结束后立刻发送，因此前端可以实时显示运行进度，不必等最终答案返回。

v3 当前只保留综合评分 `>= 0.9` 的候选文档。这个阈值由代码常量统一控制，检索事件和错误文案都会返回同一个值。如果没有任何候选文档达到阈值，v3 会继续请求 Kimi，但会在提示词中明确注入“未找到本地 SOP 文档”，并且不向模型暴露 `readFile` 工具。

## Moonshot Runtime

环境变量：

```bash
MOONSHOT_API_KEY=...
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k2.6
MOONSHOT_MAX_TOKENS=30000
MOONSHOT_TEMPERATURE=1
MOONSHOT_MAX_RETRIES=3
MOONSHOT_RETRY_BASE_SECONDS=0.75
MOONSHOT_RETRY_MAX_SECONDS=8
```

兼容性回退变量：

- `KIMI_API_KEY`
- `kimi_api_key`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Moonshot runtime 会对 `429/5xx` 和网络错误执行指数退避重试。遇到 token limit 的 `400` 错误时，Agent 会压缩历史消息和工具输出后再重试一次。

v3 WebSocket session 默认 300 秒过期，最多保留 128 个待握手 session。可以通过 `V3_SESSION_TTL_SECONDS`、`V3_MAX_SESSIONS` 和 `V3_WS_URL` 覆盖。

## 验证命令

```bash
node --check webui/app.js
uv run python -m py_compile database/db.py database/chroma_store.py v2/chunker.py v2/semantic.py v2/search.py v2/server.py v3/*.py
uv run python -m unittest v3/test_v3.py
bash -n run_all.sh
```

更细的版本文档见：

- `v1/readme.md`
- `v2/readme.md`
- `v3/readme.md`
- `webui/readme.md`
