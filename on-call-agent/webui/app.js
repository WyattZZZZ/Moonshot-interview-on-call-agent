(function () {
  const DEFAULT_API_BASE = "http://127.0.0.1:8000";
  const API_BASE_KEY = "API_BASE";
  const SEARCH_VIEWS = new Set(["v1", "v2"]);

  const versionTabs = Array.from(document.querySelectorAll(".version-tab"));
  const modeHeading = document.querySelector("#modeHeading");
  const modeCopy = document.querySelector("#modeCopy");
  const searchView = document.querySelector("#searchView");
  const chatView = document.querySelector("#chatView");
  const uploadEndpoint = document.querySelector("#uploadEndpoint");
  const searchEndpoint = document.querySelector("#searchEndpoint");

  const uploadForm = document.querySelector("#uploadForm");
  const docIdInput = document.querySelector("#docIdInput");
  const htmlFileInput = document.querySelector("#htmlFileInput");
  const htmlTextInput = document.querySelector("#htmlTextInput");
  const replaceInput = document.querySelector("#replaceInput");
  const clearUpload = document.querySelector("#clearUpload");
  const uploadStatus = document.querySelector("#uploadStatus");

  const searchForm = document.querySelector("#searchForm");
  const queryInput = document.querySelector("#queryInput");
  const resultsList = document.querySelector("#resultsList");
  const statusMessage = document.querySelector("#statusMessage");
  const resultMeta = document.querySelector("#resultMeta");
  const resultsSection = document.querySelector(".results-section");

  const chatForm = document.querySelector("#chatForm");
  const chatInput = document.querySelector("#chatInput");
  const chatMessages = document.querySelector("#chatMessages");
  const lexicalWeightInput = document.querySelector("#lexicalWeightInput");
  const weightValue = document.querySelector("#weightValue");

  let currentView = "v1";
  let chatHistory = [];
  let sessionApiBase = "";

  function validView(value) {
    return ["v1", "v2", "v3"].includes(value) ? value : null;
  }

  function readUrlApiBase() {
    const params = new URLSearchParams(window.location.search);
    return params.get("api_base") || params.get("apiBase") || "";
  }

  function readStoredApiBase() {
    try {
      return localStorage.getItem(API_BASE_KEY);
    } catch (_error) {
      return null;
    }
  }

  function writeStoredApiBase(value) {
    try {
      if (value) {
        localStorage.setItem(API_BASE_KEY, value);
      } else {
        localStorage.removeItem(API_BASE_KEY);
      }

      return true;
    } catch (_error) {
      return false;
    }
  }

  function writeUrlApiBase(value) {
    const url = new URL(window.location.href);
    if (value) {
      url.searchParams.set("api_base", value);
    } else {
      url.searchParams.delete("api_base");
      url.searchParams.delete("apiBase");
    }

    window.history.replaceState({}, "", url);
  }

  function getApiBase() {
    return String(sessionApiBase || readUrlApiBase() || readStoredApiBase() || DEFAULT_API_BASE).replace(/\/+$/, "");
  }

  function endpoint(path) {
    return `${getApiBase()}${path}`;
  }

  function setStatus(message, isError) {
    statusMessage.textContent = message;
    statusMessage.classList.toggle("error", Boolean(isError));
  }

  function setUploadStatus(message, isError) {
    uploadStatus.textContent = message;
    uploadStatus.classList.toggle("error", Boolean(isError));
  }

  function setSearchBusy(isBusy) {
    resultsSection.setAttribute("aria-busy", String(isBusy));
    searchForm.querySelector("button").disabled = isBusy;
  }

  function setUploadBusy(isBusy) {
    uploadForm.querySelector("button[type='submit']").disabled = isBusy;
  }

  function normalizeResults(payload) {
    if (Array.isArray(payload)) {
      return payload;
    }

    if (Array.isArray(payload.results)) {
      return payload.results;
    }

    if (Array.isArray(payload.items)) {
      return payload.items;
    }

    return [];
  }

  function summarizeMatchedChunk(chunk) {
    if (!chunk) {
      return "";
    }

    if (typeof chunk === "string") {
      return chunk;
    }

    if (typeof chunk !== "object") {
      return String(chunk);
    }

    const text = chunk.text || chunk.content || chunk.snippet || chunk.body || "";
    const parts = [];

    if (chunk.title) {
      parts.push(`title: ${chunk.title}`);
    }

    if (chunk.heading) {
      parts.push(`heading: ${chunk.heading}`);
    }

    if (chunk.id || chunk.chunk_id || chunk.chunkId) {
      parts.push(`chunk: ${chunk.id || chunk.chunk_id || chunk.chunkId}`);
    }

    if (text) {
      parts.push(text);
    }

    if (parts.length) {
      return parts.join("\n");
    }

    return JSON.stringify(chunk, null, 2);
  }

  function formatScore(score) {
    if (typeof score === "number" && Number.isFinite(score)) {
      return score.toFixed(3);
    }

    if (score === null || score === undefined || score === "") {
      return "n/a";
    }

    return String(score);
  }

  async function errorFromResponse(response, fallback) {
    try {
      const payload = await response.json();
      if (payload && typeof payload.error === "string" && payload.error) {
        return payload.error;
      }

      if (payload && typeof payload.detail === "string" && payload.detail) {
        return payload.detail;
      }
    } catch (_error) {
      // Ignore non-JSON error bodies and use the fallback below.
    }

    return fallback;
  }

  function renderResults(results, query) {
    resultsList.replaceChildren();
    resultMeta.textContent = `${results.length} 条结果`;

    if (!results.length) {
      setStatus(`没有找到 "${query}" 的结果。`, false);
      return;
    }

    setStatus(`正在显示 ${currentView} 对 "${query}" 的匹配结果。`, false);

    for (const item of results) {
      const li = document.createElement("li");
      li.className = "result-item";

      const titleRow = document.createElement("div");
      titleRow.className = "result-title-row";

      const title = document.createElement("h3");
      title.className = "result-title";
      title.textContent = item.title || "(untitled)";

      const score = document.createElement("span");
      score.className = "score";
      score.textContent = `score ${formatScore(item.score)}`;

      const snippet = document.createElement("p");
      snippet.className = "snippet";
      snippet.textContent = item.snippet || "";

      const id = document.createElement("span");
      id.className = "result-id";
      id.textContent = `id: ${item.id ?? "n/a"}`;

      const matchedChunkText = summarizeMatchedChunk(item.matched_chunk);
      if (matchedChunkText) {
        const matchedChunk = document.createElement("details");
        matchedChunk.className = "matched-chunk";

        const summary = document.createElement("summary");
        summary.textContent = "命中 chunk";

        const pre = document.createElement("pre");
        pre.textContent = matchedChunkText;

        matchedChunk.append(summary, pre);
        li.append(titleRow, snippet, matchedChunk, id);
      } else {
        li.append(titleRow, snippet, id);
      }

      titleRow.append(title, score);
      resultsList.append(li);
    }
  }

  function readViewFromUrl() {
    const url = new URL(window.location.href);
    const queryView = validView(url.searchParams.get("view"));
    if (queryView) {
      return queryView;
    }

    const hashView = validView(url.hash.replace(/^#\/?/, "").split(/[/?&]/)[0]);
    if (hashView) {
      return hashView;
    }

    const pathView = validView(url.pathname.split("/").filter(Boolean).pop());
    return pathView || "v1";
  }

  function syncUrl(options = {}) {
    const url = new URL(window.location.href);
    url.searchParams.set("view", currentView);

    const query = queryInput.value.trim();
    if (SEARCH_VIEWS.has(currentView) && query) {
      url.searchParams.set("q", query);
    } else {
      url.searchParams.delete("q");
    }

    url.searchParams.delete("api_base");
    url.searchParams.delete("apiBase");

    url.hash = currentView;

    if (!options.skipHistory) {
      window.history.replaceState({}, "", url);
    }
  }

  function updateWeightDisplay() {
    const lexical = Number(lexicalWeightInput.value);
    const semantic = 100 - lexical;
    weightValue.textContent = `词频 ${lexical}% / 语义 ${semantic}%`;
  }

  function currentWeights() {
    const lexical = Number(lexicalWeightInput.value) / 100;
    return {
      lexical_weight: Number(lexical.toFixed(2)),
      semantic_weight: Number((1 - lexical).toFixed(2)),
    };
  }

  function backendErrorMessage(error, path) {
    const baseMessage = error.message || "Request failed.";
    if (/HTTP 404/.test(baseMessage)) {
      return `${baseMessage}. 当前后端可能没有暴露 ${path}，请检查 API base 或启动对应的 v${currentView.slice(1)} 后端。`;
    }

    if (/Failed to fetch|NetworkError|Load failed/i.test(baseMessage)) {
      return `${baseMessage}. 请确认 API 网关已启动且 CORS 配置正确。`;
    }

    return baseMessage;
  }

  function setActiveView(nextView) {
    currentView = validView(nextView) || "v1";

    for (const tab of versionTabs) {
      const isActive = tab.dataset.view === currentView;
      tab.classList.toggle("active", isActive);
      if (isActive) {
        tab.setAttribute("aria-current", "page");
      } else {
        tab.removeAttribute("aria-current");
      }
    }

    const isSearchView = SEARCH_VIEWS.has(currentView);
    searchView.classList.toggle("hidden", !isSearchView);
    chatView.classList.toggle("hidden", isSearchView);

    if (currentView === "v1") {
      modeHeading.textContent = "v1 关键词检索";
      modeCopy.textContent = "上传 SOP HTML，然后使用关键词检索接口查询。";
    } else if (currentView === "v2") {
      modeHeading.textContent = "v2 语义检索";
      modeCopy.textContent = "使用同一套上传和搜索流程，调用 v2 语义检索接口。";
    } else {
      modeHeading.textContent = "v3 Agent 聊天";
      modeCopy.textContent = "提问值班问题，并实时查看检索、模型状态和工具调用。";
    }

    uploadEndpoint.textContent = `POST /${currentView}/documents`;
    searchEndpoint.textContent = `GET /${currentView}/search`;
    resultsList.replaceChildren();
    resultMeta.textContent = "尚未搜索";
    setStatus(`输入问题后搜索 ${currentView} 后端。`, false);
    syncUrl();
  }

  async function search(query) {
    const trimmed = query.trim();
    queryInput.value = trimmed;
    syncUrl();

    if (!trimmed) {
      resultsList.replaceChildren();
      resultMeta.textContent = "尚未搜索";
      setStatus(`输入问题后搜索 ${currentView} 后端。`, false);
      return;
    }

    setSearchBusy(true);
    setStatus("搜索中...", false);
    resultMeta.textContent = "加载中";

    try {
      const path = `/${currentView}/search?q=${encodeURIComponent(trimmed)}`;
      const response = await fetch(endpoint(path), {
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error(await errorFromResponse(response, `Backend returned HTTP ${response.status}`));
      }

      const payload = await response.json();
      renderResults(normalizeResults(payload), trimmed);
    } catch (error) {
      resultsList.replaceChildren();
      resultMeta.textContent = "搜索失败";
      setStatus(backendErrorMessage(error, `/${currentView}/search`), true);
    } finally {
      setSearchBusy(false);
    }
  }

  function inferDocId(file) {
    if (!file || docIdInput.value.trim()) {
      return;
    }

    const name = file.name.replace(/\.(html?|HTML?)$/, "");
    docIdInput.value = name || "";
  }

  async function readUploadHtml() {
    const pasted = htmlTextInput.value.trim();
    if (pasted) {
      return pasted;
    }

    const file = htmlFileInput.files && htmlFileInput.files[0];
    if (!file) {
      throw new Error("请选择 HTML 文件或粘贴 HTML 内容。");
    }

    return await file.text();
  }

  async function uploadDocument() {
    const docId = docIdInput.value.trim();
    if (!docId) {
      throw new Error("文档 ID 必填。");
    }

    const html = await readUploadHtml();
    const response = await fetch(endpoint(`/${currentView}/documents`), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ id: docId, html, replace: replaceInput.checked }),
    });

    if (!response.ok) {
      throw new Error(await errorFromResponse(response, `Upload failed with HTTP ${response.status}`));
    }

    return await response.json();
  }

  function appendChatMessage(role, content) {
    const empty = chatMessages.querySelector(".chat-empty");
    if (empty) {
      empty.remove();
    }

    const message = document.createElement("article");
    message.className = `chat-message ${role}`;
    message.dataset.role = role;

    const label = document.createElement("div");
    label.className = "chat-role";
    label.textContent = role === "user" ? "你" : "Agent";

    const body = document.createElement("div");
    body.className = "chat-body markdown";

    if (content) {
      renderMarkdown(body, content);
    }

    const trace = document.createElement("div");
    trace.className = "chat-trace";

    const status = document.createElement("div");
    status.className = "chat-status";
    if (role !== "user") {
      status.textContent = "等待会话创建...";
    }

    message.append(label, status, body, trace);
    chatMessages.append(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return {
      element: message,
      body,
      trace,
      status,
      setBody(markdown) {
        renderMarkdown(body, markdown || "");
      },
      setStatus(text, isError = false) {
        status.textContent = text || "";
        status.classList.toggle("error", Boolean(isError));
      },
      appendTrace(node) {
        trace.append(node);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      },
      markError(text) {
        message.classList.add("error");
        this.setStatus(text, true);
      },
    };
  }

  function renderSteps(container, steps) {
    if (!Array.isArray(steps) || !steps.length) {
      return;
    }

    const list = document.createElement("ol");
    list.className = "steps-list";

    for (const step of steps) {
      const item = document.createElement("li");
      const type = document.createElement("strong");
      type.textContent = step.type || "step";

      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(step, null, 2);

      item.append(type, pre);
      list.append(item);
    }

    container.append(list);
  }

  function renderCandidates(container, candidates) {
    if (!Array.isArray(candidates) || !candidates.length) {
      return;
    }

    const details = document.createElement("details");
    details.className = "candidate-list";

    const summary = document.createElement("summary");
    summary.textContent = `候选文档 (${candidates.length})`;

    const list = document.createElement("ol");
    for (const candidate of candidates) {
      const item = document.createElement("li");
      const title = candidate.title || candidate.id || candidate.filename || "candidate";
      item.textContent = `${title} · ${candidate.filename || "n/a"} · 综合 ${formatScore(candidate.combined_score)} · 词频 ${formatScore(candidate.keyword_score)} · 语义 ${formatScore(candidate.semantic_score)}`;
      list.append(item);
    }

    details.append(summary, list);
    container.append(details);
  }

  function parseInlineMarkdown(text) {
    const fragment = document.createDocumentFragment();
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
    let lastIndex = 0;
    let match;

    while ((match = pattern.exec(text)) !== null) {
      if (match.index > lastIndex) {
        fragment.append(document.createTextNode(text.slice(lastIndex, match.index)));
      }

      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        fragment.append(code);
      } else if (token.startsWith("**")) {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        fragment.append(strong);
      } else if (token.startsWith("*")) {
        const em = document.createElement("em");
        em.textContent = token.slice(1, -1);
        fragment.append(em);
      } else if (token.startsWith("[")) {
        const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (linkMatch) {
          const anchor = document.createElement("a");
          anchor.textContent = linkMatch[1];
          anchor.href = safeUrl(linkMatch[2]);
          anchor.target = "_blank";
          anchor.rel = "noreferrer";
          fragment.append(anchor);
        } else {
          fragment.append(document.createTextNode(token));
        }
      }

      lastIndex = match.index + token.length;
    }

    if (lastIndex < text.length) {
      fragment.append(document.createTextNode(text.slice(lastIndex)));
    }

    return fragment;
  }

  function safeUrl(url) {
    try {
      const parsed = new URL(url, window.location.href);
      if (["http:", "https:", "mailto:"].includes(parsed.protocol)) {
        return parsed.href;
      }
    } catch (_error) {
      // Fall through to about:blank.
    }
    return "about:blank";
  }

  function renderMarkdown(container, markdown) {
    container.replaceChildren();
    const source = String(markdown || "").replace(/\r\n/g, "\n");
    if (!source.trim()) {
      return;
    }

    const lines = source.split("\n");
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const codeFence = line.match(/^```(\w+)?\s*$/);
      if (codeFence) {
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length && /^```/.test(lines[index])) {
          index += 1;
        }

        const pre = document.createElement("pre");
        pre.className = "md-code";
        const code = document.createElement("code");
        if (codeFence[1]) {
          code.dataset.language = codeFence[1];
        }
        code.textContent = codeLines.join("\n");
        pre.append(code);
        container.append(pre);
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = heading[1].length;
        const tag = `h${level}`;
        const el = document.createElement(tag);
        el.className = "md-heading";
        el.append(parseInlineMarkdown(heading[2]));
        container.append(el);
        index += 1;
        continue;
      }

      const quote = line.match(/^>\s?(.*)$/);
      if (quote) {
        const blockquote = document.createElement("blockquote");
        blockquote.className = "md-quote";
        const p = document.createElement("p");
        p.append(parseInlineMarkdown(quote[1]));
        blockquote.append(p);
        index += 1;
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          const next = document.createElement("p");
          next.append(parseInlineMarkdown(lines[index].replace(/^>\s?/, "")));
          blockquote.append(next);
          index += 1;
        }
        container.append(blockquote);
        continue;
      }

      const unordered = line.match(/^[-*]\s+(.*)$/);
      const ordered = line.match(/^\d+\.\s+(.*)$/);
      if (unordered || ordered) {
        const tag = ordered ? "ol" : "ul";
        const list = document.createElement(tag);
        list.className = "md-list";
        while (index < lines.length) {
          const current = lines[index];
          const currentUnordered = current.match(/^[-*]\s+(.*)$/);
          const currentOrdered = current.match(/^\d+\.\s+(.*)$/);
          if (!currentUnordered && !currentOrdered) {
            break;
          }
          const item = document.createElement("li");
          const value = (currentUnordered || currentOrdered)[1];
          item.append(parseInlineMarkdown(value));
          list.append(item);
          index += 1;
        }
        container.append(list);
        continue;
      }

      const paragraphs = [line.trim()];
      index += 1;
      while (index < lines.length) {
        const next = lines[index];
        if (!next.trim()) {
          break;
        }
        if (/^```/.test(next) || /^(#{1,6})\s+/.test(next) || /^>\s?/.test(next) || /^[-*]\s+/.test(next) || /^\d+\.\s+/.test(next)) {
          break;
        }
        paragraphs.push(next.trim());
        index += 1;
      }

      const p = document.createElement("p");
      p.className = "md-paragraph";
      p.append(parseInlineMarkdown(paragraphs.join(" ")));
      container.append(p);
    }
  }

  function appendTraceItem(container, title, text, kind) {
    const item = document.createElement("article");
    item.className = `trace-item ${kind || ""}`.trim();

    const heading = document.createElement("div");
    heading.className = "trace-heading";
    heading.textContent = title;

    item.append(heading);

    if (text) {
      const body = document.createElement("pre");
      body.textContent = text;
      item.append(body);
    }

    container.append(item);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function appendToolTrace(container, step) {
    const title = step.ok ? `工具 ${step.name} 调用成功` : `工具 ${step.name} 调用失败`;
    const text = [
      step.arguments ? `参数: ${JSON.stringify(step.arguments)}` : "",
      step.output_preview ? `输出预览: ${step.output_preview}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    appendTraceItem(container, title, text, step.ok ? "ok" : "error");
  }

  function appendRetrievalTrace(container, event) {
    const title = `检索完成，候选文档 ${event.candidate_count || 0} 个`;
    appendTraceItem(
      container,
      title,
      `query: ${event.query || ""}\n词频权重: ${formatScore(event.keyword_weight)}\n语义权重: ${formatScore(event.semantic_weight)}\n阈值: ${formatScore(event.threshold)}`,
      "retrieval"
    );
    if (Array.isArray(event.candidates) && event.candidates.length) {
      renderCandidates(container, event.candidates);
    }
  }

  async function openChatSession(payload) {
    const response = await fetch(endpoint("/v3/chat/session"), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(await errorFromResponse(response, `Backend returned HTTP ${response.status}`));
    }

    return await response.json();
  }

  function resolveWebSocketUrl(value) {
    const raw = String(value || "/v3/chat/ws").trim();
    try {
      const parsed = new URL(raw);
      if (parsed.protocol === "ws:" || parsed.protocol === "wss:") {
        return parsed.href;
      }
    } catch (_error) {
      // Relative URL fallback below.
    }

    const base = new URL(getApiBase(), window.location.href);
    base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
    base.pathname = raw.startsWith("/") ? raw : `/${raw}`;
    base.search = "";
    base.hash = "";
    return base.href;
  }

  function streamChatSession(session, bubble, trimmedMessage) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(resolveWebSocketUrl(session.ws_url));
      let settled = false;

      const finish = (callback, value) => {
        if (settled) {
          return;
        }
        settled = true;
        callback(value);
      };

      socket.addEventListener("open", () => {
        bubble.setStatus("已连接，等待模型响应...");
        socket.send(JSON.stringify({ session_id: session.session_id }));
      });

      socket.addEventListener("message", (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch (_error) {
          appendTraceItem(bubble.trace, "Malformed websocket payload", String(event.data), "error");
          return;
        }

        if (payload.type === "status") {
          bubble.setStatus(payload.message || "Thinking...");
          appendTraceItem(bubble.trace, payload.message || "状态更新", payload.phase || "", "status");
          return;
        }

        if (payload.type === "retrieval") {
          bubble.setStatus("候选文档已准备，模型正在思考...");
          appendRetrievalTrace(bubble.trace, payload);
          return;
        }

        if (payload.type === "assistant") {
          if (payload.content) {
            appendTraceItem(bubble.trace, "模型草稿", payload.content, "assistant");
          } else {
            appendTraceItem(bubble.trace, `模型第 ${payload.round || ""} 轮`.trim(), `工具调用数: ${payload.tool_call_count || 0}`, "assistant");
          }
          bubble.setStatus("模型正在思考...");
          return;
        }

        if (payload.type === "tool") {
          appendToolTrace(bubble.trace, payload);
          bubble.setStatus(payload.ok ? "工具调用完成。" : "工具调用失败。", !payload.ok);
          return;
        }

        if (payload.type === "final") {
          bubble.setStatus("答案已生成。");
          bubble.setBody(payload.answer || "(empty answer)");
          chatHistory = [
            ...chatHistory,
            { role: "user", content: trimmedMessage },
            { role: "assistant", content: payload.answer || "" },
          ];
          finish(resolve, payload);
          socket.close();
          return;
        }

        if (payload.type === "error") {
          finish(reject, new Error(payload.message || "WebSocket 请求失败。"));
          socket.close();
        }
      });

      socket.addEventListener("error", () => {
        finish(reject, new Error("WebSocket 连接失败。"));
      });

      socket.addEventListener("close", () => {
        if (!settled) {
          finish(reject, new Error("WebSocket 在答案生成前关闭。"));
        }
      });
    });
  }

  async function sendChatMessage(message) {
    const trimmed = message.trim();
    if (!trimmed) {
      return;
    }

    appendChatMessage("user", trimmed);
    chatInput.value = "";
    const pending = appendChatMessage("agent", "");
    pending.setStatus("正在创建会话...");
    chatForm.querySelector("button").disabled = true;

    try {
      const session = await openChatSession({ message: trimmed, history: chatHistory, ...currentWeights() });
      pending.setStatus("会话已创建，等待模型响应...");
      await streamChatSession(session, pending, trimmed);
    } catch (error) {
      pending.markError(backendErrorMessage(error, "/v3/chat/session"));
      if (!pending.body.textContent.trim()) {
        pending.setBody(backendErrorMessage(error, "/v3/chat/session"));
      }
    } finally {
      chatForm.querySelector("button").disabled = false;
    }
  }

  versionTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setActiveView(tab.dataset.view);
    });
  });

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    search(queryInput.value);
  });

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    setUploadBusy(true);
    setUploadStatus("上传中...", false);

    try {
      const payload = await uploadDocument();
      const title = payload.title ? ` (${payload.title})` : "";
      setUploadStatus(`已上传 ${payload.id || docIdInput.value}${title}。`, false);
    } catch (error) {
      setUploadStatus(backendErrorMessage(error, `/${currentView}/documents`), true);
    } finally {
      setUploadBusy(false);
    }
  });

  htmlFileInput.addEventListener("change", () => {
    const file = htmlFileInput.files && htmlFileInput.files[0];
    inferDocId(file);
  });

  clearUpload.addEventListener("click", () => {
    uploadForm.reset();
    setUploadStatus("尚未上传", false);
  });

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendChatMessage(chatInput.value);
  });

  lexicalWeightInput.addEventListener("input", updateWeightDisplay);

  window.addEventListener("popstate", () => {
    setActiveView(readViewFromUrl());
  });

  window.addEventListener("hashchange", () => {
    setActiveView(readViewFromUrl());
  });

  updateWeightDisplay();

  sessionApiBase = readUrlApiBase();
  const params = new URLSearchParams(window.location.search);
  setActiveView(readViewFromUrl());

  const initialQuery = params.get("q") || "";
  queryInput.value = initialQuery;

  if (initialQuery && SEARCH_VIEWS.has(currentView)) {
    search(initialQuery);
  }
})();
