# On-Call Agent v3

v3 是工具调用 Agent 层。它会先执行检索，只把高置信候选文档交给模型，并只暴露一个受限的文件读取工具。

## Runtime

运行时使用 Moonshot 的 OpenAI-compatible Chat Completions API。

默认配置：

```bash
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_MODEL=kimi-k2.6
MOONSHOT_MAX_TOKENS=30000
MOONSHOT_TEMPERATURE=1
```

密钥变量：

```bash
MOONSHOT_API_KEY=...
```

兼容别名：

- `KIMI_API_KEY`
- `kimi_api_key`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OPENAI_MAX_TOKENS`
- `OPENAI_TEMPERATURE`

可靠性相关变量：

```bash
MOONSHOT_MAX_RETRIES=3
MOONSHOT_RETRY_BASE_SECONDS=0.75
MOONSHOT_RETRY_MAX_SECONDS=8
V3_SESSION_TTL_SECONDS=300
V3_MAX_SESSIONS=128
V3_WS_URL=
```

Moonshot runtime 会对 `429/500/502/503/504` 和网络错误做指数退避重试。遇到 token limit 的 `400` 错误时，Agent 会压缩候选元数据、历史消息和工具输出后重试一次。

## 检索流程

对每个用户 query，v3 会：

1. 针对 SQLite FTS5 执行 v1 关键词搜索
2. 针对 Chroma 执行 v2 语义搜索
3. 分别归一化两组分数
4. 计算 `combined_score = keyword_weight * keyword_score + semantic_weight * semantic_score`
5. 只保留 `combined_score >= 0.9` 的候选文档

v1 和 v2 检索通过 `ThreadPoolExecutor(max_workers=2)` 并行执行。v3 在进程内导入 v1/v2 search 模块，不调用 v1/v2 HTTP API。

如果没有任何文档达到阈值，v3 不会直接返回失败。它会继续请求 Kimi，并在 system prompt 中注入“未找到本地 SOP 文档”的提示，让模型基于通用值班推理回答，同时要求模型明确告知用户没有命中的本地 SOP。此时不会向模型暴露 `readFile` 工具。

## 工具契约

模型唯一可用工具是：

```text
readFile(fname: string) -> string
```

安全规则：

- `fname` 必须是候选文档文件名之一
- 路径、绝对路径、嵌套路径和通配符都会被拒绝
- harness 会把 `fname` 拼接到 `../coding-exam/question-1/data`
- 模型永远不会看到本地文件系统路径

非法工具调用会作为失败的 tool message 返回给模型，让模型在工具循环内自行修正。

## 上下文管理

前端会发送 `history`；服务端会清洗为 user/assistant 消息，并只保留最近 12 条。服务端还会在用户消息前发送压缩后的候选文档元数据。完整文档内容只会在模型调用 `readFile` 后加入上下文。

工具调用轮数由 `MAX_TOOL_ROUNDS = 4` 限制。

WebSocket session 默认 300 秒过期，最多保留 128 个等待握手的 session。session 在成功握手后会被立即消费，不能复用。

## API

同步聊天：

```bash
curl -sS http://127.0.0.1:8000/v3/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"OOM 怎么处理？","history":[],"weights":{"keyword":0.5,"semantic":0.5}}'
```

流式聊天会话：

```bash
curl -sS http://127.0.0.1:8000/v3/chat/session \
  -H 'Content-Type: application/json' \
  -d '{"message":"OOM 怎么处理？","history":[],"weights":{"keyword":0.5,"semantic":0.5}}'
```

响应包含：

```json
{
  "session_id": "...",
  "ws_url": "ws://127.0.0.1:8004/v3/chat/ws"
}
```

连接 `ws_url` 后发送：

```json
{"session_id":"..."}
```

WebSocket 事件类型：

- `status`：面向用户的运行进度
- `retrieval`：query、权重、阈值、候选数量和候选列表
- `assistant`：模型轮次元数据和可选的 assistant 草稿
- `tool`：一次已完成的工具调用，包含参数、成功标记和输出预览
- `final`：最终答案、候选文档和 trace 摘要
- `error`：终止性的运行错误

Web UI 会用这些事件实时展示工具调用进度。

如果浏览器刷新、关闭页面或网络断开导致 WebSocket 先关闭，服务端会停止发送剩余事件并安静结束连接，不会再向已关闭连接发送错误消息。

如果通过代理或远端机器访问，可以设置 `V3_WS_URL` 返回浏览器可访问的 WebSocket 地址。

## 启动

```bash
cd on-call-agent
uv sync
uv run python v3/server.py \
  --host 127.0.0.1 \
  --port 8003 \
  --ws-port 8004 \
  --data-dir ../coding-exam/question-1/data
```

日常开发建议使用 `./run_all.sh`，这样 v1、v2、v3、gateway 和 webui 会一起启动。

## 测试

```bash
uv run python -m unittest v3/test_v3.py
```

测试使用 fake runtime 和注入的检索函数，因此不需要 Moonshot key、Chroma 或模型下载。
