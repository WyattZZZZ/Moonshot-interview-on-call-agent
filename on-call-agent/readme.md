# Moonshot On-Call Agent

This app uses `uv` for its Python environment.

## Environment

From this directory:

```bash
uv sync
```

Run Python commands through the project environment:

```bash
uv run python v1/server.py --host 127.0.0.1 --port 8000 --import-demo
```

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
