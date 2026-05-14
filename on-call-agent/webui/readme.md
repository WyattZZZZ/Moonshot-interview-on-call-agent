# on-call-agent webui

Static HTML/CSS/JS UI for the versioned on-call assistant routes.

## Open

Open `index.html` directly in a browser:

```text
on-call-agent/webui/index.html
```

No build step or package install is required.

## Backend

Start the v1 backend from `on-call-agent/`:

```bash
uv run python v1/server.py --host 127.0.0.1 --port 8000 --import-demo
```

The UI calls these versioned endpoints:

```text
POST /v1/documents
GET  /v1/search?q=...
POST /v2/documents
GET  /v2/search?q=...
POST /v3/chat
```

By default, requests are sent to:

```text
http://localhost:8000
```

To point the page at another backend, open the API panel in the page and save a new base URL. The value is stored in:

```js
localStorage.API_BASE
```

You can also set it manually in the browser console:

```js
localStorage.setItem("API_BASE", "http://localhost:8000");
```

The saved base URL should not include route paths; the UI appends `/v1/...`, `/v2/...`, or `/v3/...` automatically.

## Views

- `v1`: HTML upload plus keyword search.
- `v2`: Same upload and search UI shape as v1, pointed at v2 endpoints.
- `v3`: Agent chat UI that sends `{ "message": "...", "history": [...] }` and renders `answer` plus optional `steps`.

## URL query sync

The search form keeps `?view=...&q=...` in sync with the current query. Loading the page with a URL such as:

```text
index.html?view=v1&q=database
```

automatically opens that version and runs search for v1/v2.
