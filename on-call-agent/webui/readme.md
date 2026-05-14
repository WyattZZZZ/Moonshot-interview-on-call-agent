# On-Call Agent Web UI

这是 v1、v2、v3 路由的静态浏览器界面。

## 启动

最简单的方式是使用项目启动脚本：

```bash
cd on-call-agent
./run_all.sh
```

脚本会在下面的地址启动静态 UI：

```text
http://127.0.0.1:4173/#v1
```

UI 没有构建步骤，也可以手动启动：

```bash
uv run python -m http.server 4173 --bind 127.0.0.1 --directory webui
```

## API Base

默认 API base：

```text
http://127.0.0.1:8000
```

API 面板会把覆盖配置存入：

```js
localStorage.API_BASE
```

页面也接受：

```text
?api_base=<api-base-url>
```

UI 会自己追加版本路径，因此保存的 base URL 不应该包含 `/v1`、`/v2` 或 `/v3`。

## 视图

- `v1`：文档上传和关键词搜索
- `v2`：文档上传和语义搜索
- `v3`：带检索权重滑块的 Agent 聊天

当前视图会同步到 `?view=...` 和 `#v...`。例如：

```text
http://127.0.0.1:4173/?view=v3#v3
```

## v3 流式聊天

v3 聊天界面使用 WebSocket 流式输出：

1. `POST /v3/chat/session`
2. 打开返回的 `ws_url`
3. 发送 `{"session_id":"..."}`
4. 按到达顺序渲染事件

界面会显示的运行时事件：

- 候选文档检索和打分
- 模型思考轮次
- 每一次完成的 `readFile` 工具调用
- 最终答案
- 运行时错误

最终答案会按基础 Markdown 渲染。支持标题、段落、有序列表、无序列表、引用、加粗、斜体、行内代码、链接和 fenced code block。代码块和 trace payload 会被限制在聊天气泡内部，横向溢出时只在气泡内滚动。

## 验证

```bash
node --check webui/app.js
```

手动检查：

1. 打开 v3 页签
2. 提问 `服务 OOM 了怎么办？`
3. 确认 trace 中显示检索、模型状态、`readFile` 和最终 Markdown 答案
