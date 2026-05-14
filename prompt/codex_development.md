
› 阅读本项目下的prompt中的chatgpt_api_plan.md来理解实现方案

---

› v1是非常简单的，你分派两个agent，一个实现v1，一个实现所有webui，在他们对应的文件夹下，记得共享基础设施要生成在on-call-agent的database目录中，然后注意data中建表要考虑v2，提前做好schema兼容，也就是说向量属性要有，但是选填，后期实现v2会有填写逻辑

---

› 我使用了v1的webui的搜索，然后搜索结果的score是0，且没有用jieba分词

---

› 在on-call-agent中使用uv作为环境

---

› 检查现在是否每次启动服务器都会重置数据库，检查上传/删除出错兜底策略，比如id重复，文件太长

---

› 好了，现在分出一个agent去处理v2的功能，注意上述在v1中检查到问题，例如分词，兜底策略等等

---

› 告诉我你的embedding模型是什么，introduction如何生成，全文怎么embedding分块？数据如何存储在sqlite中

---

› 现在将基于jieba的策略都删除，换成embedding数据，使用openai提供的embdedding模型，文件的introduction不用做了，按照html的heading标签分块，过于简短的块，比如小于10个字符的块直接过滤掉，然后使用chroma装这些数据

---

› 换用本地的ebedding模型，BAAI/bge-small-zh-v1.5，使用hf镜像安装

---


› 现在启动3个agent，第一个完成v2没有做完的事情，修复bug，直到跑通为止，一个去修复webui，包括v2，v3没有路由的问题，将webui根据tab定位到v1，v2，v3，并且在v3上加入一个滑块，用来控制词频和语义的权重比例。第三个完整实现agent功能，自己实现测试，阅读完善文档，使用moonshot的api作为runtime，记住还有agent tool只有read file，且只能读coding exam中question1的data目录，使用方式只能是模型给出文件名，harness拼接路径，返回文件，模型本身看不到路径，在请求agent前将query过一遍v1和v2的api用来得到词频和语义的分数然后返回综合评分（webui中权重会指定）0.9以上的文档，然后给模型让模型选择阅读，记住harness要实现上下文管理，历史对话管理，工具调用等。现在我要去吃饭，你不要rm -rf 然后我给你开房所有权限。

---

› 现在创建一个sh文件和一个bat文件，一键拉起所有服务，启动前端

---

› double check有没有检测端口被占用后的兜底策略，有没有agent的流式输出和tool call解析，告诉我解析逻辑是怎样的，检测前端是否真的可以读取到后端回传的tool call/query查询等输入输出，检测chroma和sqlite的搜索策略是否并行，测试kimi api能否
  成功调用，告诉我你的prompt注入策略是怎样的

---

› 检测agent重试策略和fallback回滚设计，保证失败后恢复上一时刻状态，告诉我工具调用/api调用等报错的重试策略，是否有做指数退避和最大上限，分出一个子agent，让他探索webui和agent之间的通讯关系，api握手成功后建立websocket链接流式输出

---

› 我测试了一下，检查前端和现在api的端口映射，我调用v1/v2都显示的fetch fail 8000端口, chrome console 显示，CROS问题，错误如下，你需要去检查gateway设置: ...

---

› 重新测试agent的kimi runtime

---

› Moonshot API HTTP 400: 请求超过 8192 token 上限。将 v3 默认模型切到 `kimi-k2.6`，默认 `MOONSHOT_MAX_TOKENS=30000`，并把 temperature 设为该模型要求的 `1`。同时修复 `.env` 中 `kimi_api_key` 的兼容读取。

---

› 检查 v3 是否通过 HTTP 调 v2。结论：v3 当前不是走 v2 HTTP API，而是在进程内导入 `v2/search.py` 并调用 `search_documents_semantic`。为避免旧的半加载模块导致 `search_documents_semantic` 缺失，模块加载器增加 expected attr 校验；为避免并发请求重复加载 embedding model，`v2/semantic.py` 使用线程安全单例。

---

› 修复 v3 Web UI 无法实时显示工具调用的问题。新增 `POST /v3/chat/session` 和 `ws://127.0.0.1:8004/v3/chat/ws`。前端先创建 session，再通过 WebSocket 接收 `status`、`retrieval`、`assistant`、`tool`、`final`、`error` 事件。每次 `readFile` 工具调用完成后立即回传 `tool` 事件，前端实时显示运行轨迹。

---

› 修复聊天气泡渲染。前端新增基础 Markdown 渲染，支持标题、列表、引用、粗体、斜体、行内 code、链接和 fenced code block。代码块和 tool trace 使用 constrained overflow，避免背景和文本超出聊天气泡。

---

› 清理前端可见的旧 loopback host 文本。Web UI 默认和示例统一为 `http://127.0.0.1:8000`，但仍兼容旧 localStorage 中保存的 localhost API base。

---

› function getApiBase() {
    function normalizeApiBase(value) {
      const stripped = String(value || DEFAULT_API_BASE).replace(/\/+$/, "");
      try {
        const url = new URL(stripped);
        if (url.protocol === "http:" && url.hostname === "localhost" && url.port === "8000") {
          return DEFAULT_API_BASE;
        }
      } catch (_) {
        return stripped;
      }
      return stripped;
    } 这个ui的逻辑直接删除，会导致8000端口的信息一直出现在界面上

---

› 将每个on-call-agent中readme文件都写成中文

---

# Current Architecture Summary

## Services

- v1 backend: `127.0.0.1:8001`
- v2 backend: `127.0.0.1:8002`
- v3 HTTP backend: `127.0.0.1:8003`
- v3 WebSocket stream: `127.0.0.1:8004`
- API gateway: `127.0.0.1:8000`
- static Web UI: `127.0.0.1:4173`

`run_all.sh` and `run_all.bat` start all services and preflight-check occupied ports. The gateway routes `/v1`, `/v2`, and `/v3` to their local backends and owns browser-facing CORS headers.

## Data

- SQLite: `on-call-agent/database/on_call_agent.sqlite3`
- Chroma: `on-call-agent/database/chroma/`
- Source SOP HTML: `coding-exam/question-1/data`

v1 and v2 share document rows in SQLite. v2 stores active semantic vectors in Chroma. v3 reads candidate filenames only from retrieval results and allows tool reads only from the fixed SOP data directory.

## Version Responsibilities

v1 is keyword retrieval with SQLite FTS5 and jieba tokenization. It provides document upload/get/delete and keyword search.

v2 is semantic retrieval with local `BAAI/bge-small-zh-v1.5` embeddings. It chunks HTML by heading tags, filters tiny chunks, stores vectors in Chroma, and returns matched chunk metadata.

v3 is the agent harness. It runs v1 and v2 retrieval in parallel, fuses scores with Web UI weights, keeps high-confidence candidates, calls Moonshot/Kimi, handles history and context, and exposes only `readFile(fname)`.

Web UI is static HTML/CSS/JS. It has v1/v2 search tabs and a v3 streaming chat tab. v3 chat renders runtime tool events over WebSocket and final answers as Markdown.
