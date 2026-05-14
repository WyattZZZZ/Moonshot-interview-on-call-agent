(function () {
  const DEFAULT_API_BASE = "http://localhost:8000";
  const API_BASE_KEY = "API_BASE";
  const SEARCH_VIEWS = new Set(["v1", "v2"]);

  const versionTabs = Array.from(document.querySelectorAll(".version-tab"));
  const modeHeading = document.querySelector("#modeHeading");
  const modeCopy = document.querySelector("#modeCopy");
  const searchView = document.querySelector("#searchView");
  const chatView = document.querySelector("#chatView");
  const uploadEndpoint = document.querySelector("#uploadEndpoint");
  const searchEndpoint = document.querySelector("#searchEndpoint");

  const settingsToggle = document.querySelector("#settingsToggle");
  const settingsPanel = document.querySelector("#settingsPanel");
  const apiBaseInput = document.querySelector("#apiBaseInput");
  const saveApiBase = document.querySelector("#saveApiBase");
  const resetApiBase = document.querySelector("#resetApiBase");

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

  let currentView = "v1";
  let chatHistory = [];

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

  function getApiBase() {
    return (readStoredApiBase() || DEFAULT_API_BASE).replace(/\/+$/, "");
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
    } catch (_error) {
      // Ignore non-JSON error bodies and use the fallback below.
    }

    return fallback;
  }

  function renderResults(results, query) {
    resultsList.replaceChildren();
    resultMeta.textContent = `${results.length} result${results.length === 1 ? "" : "s"}`;

    if (!results.length) {
      setStatus(`No results for "${query}".`, false);
      return;
    }

    setStatus(`Showing ${currentView} matches for "${query}".`, false);

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

      titleRow.append(title, score);
      li.append(titleRow, snippet, id);
      resultsList.append(li);
    }
  }

  function syncUrl() {
    const url = new URL(window.location.href);
    url.searchParams.set("view", currentView);

    const query = queryInput.value.trim();
    if (SEARCH_VIEWS.has(currentView) && query) {
      url.searchParams.set("q", query);
    } else {
      url.searchParams.delete("q");
    }

    window.history.replaceState({}, "", url);
  }

  function setActiveView(nextView) {
    currentView = ["v1", "v2", "v3"].includes(nextView) ? nextView : "v1";

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
      modeHeading.textContent = "v1 Keyword Search";
      modeCopy.textContent = "Upload SOP HTML, then query the keyword search endpoint.";
    } else if (currentView === "v2") {
      modeHeading.textContent = "v2 Semantic Search";
      modeCopy.textContent = "Use the same upload and search workflow against the v2 semantic endpoints.";
    } else {
      modeHeading.textContent = "v3 Agent Chat";
      modeCopy.textContent = "Ask on-call questions and inspect the agent answer plus tool steps.";
    }

    uploadEndpoint.textContent = `POST /${currentView}/documents`;
    searchEndpoint.textContent = `GET /${currentView}/search`;
    resultsList.replaceChildren();
    resultMeta.textContent = "No search yet";
    setStatus(`Enter a query to search the ${currentView} backend.`, false);
    syncUrl();
  }

  async function search(query) {
    const trimmed = query.trim();
    queryInput.value = trimmed;
    syncUrl();

    if (!trimmed) {
      resultsList.replaceChildren();
      resultMeta.textContent = "No search yet";
      setStatus(`Enter a query to search the ${currentView} backend.`, false);
      return;
    }

    setSearchBusy(true);
    setStatus("Searching...", false);
    resultMeta.textContent = "Loading";

    try {
      const response = await fetch(endpoint(`/${currentView}/search?q=${encodeURIComponent(trimmed)}`), {
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error(await errorFromResponse(response, `Backend returned HTTP ${response.status}`));
      }

      const payload = await response.json();
      renderResults(normalizeResults(payload), trimmed);
    } catch (error) {
      resultsList.replaceChildren();
      resultMeta.textContent = "Search failed";
      setStatus(error.message || "Search failed.", true);
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
      throw new Error("Choose an HTML file or paste HTML content.");
    }

    return await file.text();
  }

  async function uploadDocument() {
    const docId = docIdInput.value.trim();
    if (!docId) {
      throw new Error("Document ID is required.");
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

    const label = document.createElement("div");
    label.className = "chat-role";
    label.textContent = role === "user" ? "You" : "Agent";

    const body = document.createElement("div");
    body.className = "chat-body";
    body.textContent = content;

    message.append(label, body);
    chatMessages.append(message);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return message;
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

  async function sendChatMessage(message) {
    const trimmed = message.trim();
    if (!trimmed) {
      return;
    }

    appendChatMessage("user", trimmed);
    chatInput.value = "";
    const pending = appendChatMessage("agent", "Thinking...");
    chatForm.querySelector("button").disabled = true;

    try {
      const response = await fetch(endpoint("/v3/chat"), {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message: trimmed, history: chatHistory }),
      });

      if (!response.ok) {
        throw new Error(await errorFromResponse(response, `Backend returned HTTP ${response.status}`));
      }

      const payload = await response.json();
      const answer = payload.answer || payload.message || "";
      pending.querySelector(".chat-body").textContent = answer || "(empty answer)";
      renderSteps(pending, payload.steps);
      chatHistory = [
        ...chatHistory,
        { role: "user", content: trimmed },
        { role: "assistant", content: answer },
      ];
    } catch (error) {
      pending.querySelector(".chat-body").textContent = error.message || "Chat failed.";
      pending.classList.add("error");
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
    setUploadStatus("Uploading...", false);

    try {
      const payload = await uploadDocument();
      const title = payload.title ? ` (${payload.title})` : "";
      setUploadStatus(`Uploaded ${payload.id || docIdInput.value}${title}.`, false);
    } catch (error) {
      setUploadStatus(error.message || "Upload failed.", true);
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
    setUploadStatus("No upload yet", false);
  });

  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendChatMessage(chatInput.value);
  });

  settingsToggle.addEventListener("click", () => {
    const isHidden = settingsPanel.hidden;
    settingsPanel.hidden = !isHidden;
    settingsToggle.setAttribute("aria-expanded", String(isHidden));
  });

  saveApiBase.addEventListener("click", () => {
    const value = apiBaseInput.value.trim().replace(/\/+$/, "");

    if (!value) {
      writeStoredApiBase("");
      apiBaseInput.value = DEFAULT_API_BASE;
      setStatus("API base reset to default.", false);
      return;
    }

    if (writeStoredApiBase(value)) {
      apiBaseInput.value = value;
      setStatus(`API base set to ${value}.`, false);
    } else {
      setStatus("Browser storage is unavailable; edit DEFAULT_API_BASE in app.js instead.", true);
    }
  });

  resetApiBase.addEventListener("click", () => {
    writeStoredApiBase("");
    apiBaseInput.value = DEFAULT_API_BASE;
    setStatus("API base reset to default.", false);
  });

  apiBaseInput.value = getApiBase();

  const params = new URLSearchParams(window.location.search);
  setActiveView(params.get("view") || "v1");

  const initialQuery = params.get("q") || "";
  queryInput.value = initialQuery;

  if (initialQuery && SEARCH_VIEWS.has(currentView)) {
    search(initialQuery);
  }
})();
