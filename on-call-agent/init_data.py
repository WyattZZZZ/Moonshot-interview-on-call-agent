from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from database import db


ON_CALL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ON_CALL_ROOT.parent
V1_ROOT = ON_CALL_ROOT / "v1"
V2_ROOT = ON_CALL_ROOT / "v2"
DEFAULT_DEMO_DIR = REPO_ROOT / "coding-exam" / "question-1" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize on-call-agent SQLite and Chroma indexes before serving")
    parser.add_argument("--db", type=Path, default=db.default_db_path())
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO_DIR)
    parser.add_argument("--refresh-demo", action="store_true")
    parser.add_argument("--allow-empty", action="store_true")
    args = parser.parse_args()

    demo_dir = args.demo_dir.resolve()
    if not demo_dir.is_dir():
        raise SystemExit(f"demo dir does not exist: {demo_dir}")
    html_files = sorted(demo_dir.glob("*.html"))
    if not html_files and not args.allow_empty:
        raise SystemExit(f"demo dir contains no .html files: {demo_dir}")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db.connection(args.db) as conn:
        db.initialize(conn)

    print(f"Initializing SQLite keyword index from {demo_dir}")
    v1_server = _load_v1_server()
    v1_imported, v1_skipped = v1_server.import_demo_data(args.db, demo_dir, refresh=args.refresh_demo)
    print(f"v1 import complete: imported {v1_imported}, skipped {v1_skipped}")

    print(f"Initializing Chroma semantic index from {demo_dir}")
    v2_server = _load_v2_server()
    v2_imported, v2_skipped = v2_server.import_demo_data(args.db, demo_dir, refresh=args.refresh_demo)
    print(f"v2 import complete: imported {v2_imported}, skipped {v2_skipped}")

    with db.connection(args.db) as conn:
        db.initialize(conn)
        doc_count = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
    if int(doc_count) <= 0 and not args.allow_empty:
        raise SystemExit("database initialized but contains no documents")
    print(f"Database ready: {args.db.resolve()} ({doc_count} documents)")


def _load_v1_server():
    _prepend_paths(V1_ROOT, ON_CALL_ROOT)
    return _load_module("init_v1_server", V1_ROOT / "server.py")


def _load_v2_server():
    for name in ("search", "chunker", "semantic"):
        sys.modules.pop(name, None)
    _prepend_paths(V2_ROOT, ON_CALL_ROOT, V1_ROOT)
    return _load_module("init_v2_server", V2_ROOT / "server.py")


def _prepend_paths(*paths: Path) -> None:
    for path in reversed(paths):
        text = str(path)
        while text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    main()
