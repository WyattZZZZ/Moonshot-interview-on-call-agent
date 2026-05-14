from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .tokenizer import tokenized_text


DATABASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = DATABASE_DIR / "on_call_agent.sqlite3"


def default_db_path() -> Path:
    return Path(os.environ.get("ON_CALL_AGENT_DB", DEFAULT_DB_PATH)).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(Path(db_path).resolve() if db_path else default_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            html TEXT NOT NULL,
            clean_text TEXT NOT NULL,
            semantic_profile TEXT NULL,
            embedding TEXT NULL,
            path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            model TEXT NULL,
            vector TEXT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_documents_id ON documents(id);
        CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
        """
    )
    ensure_document_columns(conn)
    ensure_fts_schema(conn)
    rebuild_fts_if_empty(conn)


def ensure_document_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "semantic_profile" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN semantic_profile TEXT NULL")
    if "embedding" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN embedding TEXT NULL")
    if "path" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN path TEXT NOT NULL DEFAULT ''")


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        """
        SELECT sql
          FROM sqlite_master
         WHERE type = 'table'
           AND name = 'document_fts'
        """
    ).fetchone()
    if existing and "doc_id UNINDEXED" not in (existing["sql"] or ""):
        conn.execute("DROP TABLE document_fts")

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(
            doc_id UNINDEXED,
            title_terms,
            clean_text_terms,
            tokenize='unicode61'
        )
        """
    )


def rebuild_fts_if_empty(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS count FROM document_fts").fetchone()
    if row and int(row["count"]) > 0:
        return
    rows = conn.execute("SELECT id, title, clean_text FROM documents").fetchall()
    for document in rows:
        index_document_fts(
            conn,
            doc_id=document["id"],
            title=document["title"],
            clean_text=document["clean_text"],
        )


def index_document_fts(conn: sqlite3.Connection, *, doc_id: str, title: str, clean_text: str) -> None:
    conn.execute("DELETE FROM document_fts WHERE doc_id = ?", (doc_id,))
    conn.execute(
        """
        INSERT INTO document_fts(doc_id, title_terms, clean_text_terms)
        VALUES (?, ?, ?)
        """,
        (doc_id, tokenized_text(title), tokenized_text(clean_text)),
    )


def upsert_document(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    title: str,
    html: str,
    clean_text: str,
    path: str = "",
    semantic_profile: str | None = None,
    embedding: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    existing = conn.execute("SELECT rowid, created_at FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE documents
               SET title = ?, html = ?, clean_text = ?, semantic_profile = ?,
                   embedding = ?, path = ?, updated_at = ?
             WHERE id = ?
            """,
            (title, html, clean_text, semantic_profile, embedding, path, now, doc_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO documents
                (id, title, html, clean_text, semantic_profile, embedding, path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, title, html, clean_text, semantic_profile, embedding, path, now, now),
        )

    index_document_fts(conn, doc_id=doc_id, title=title, clean_text=clean_text)
    return get_document(conn, doc_id) or {}


def upsert_embedding(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    model: str,
    vector: str,
) -> dict[str, Any]:
    now = utc_now()
    conn.execute("DELETE FROM embeddings WHERE document_id = ?", (document_id,))
    conn.execute(
        """
        INSERT INTO embeddings(document_id, model, vector, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (document_id, model, vector, now),
    )
    row = conn.execute(
        """
        SELECT id, document_id, model, vector, created_at
          FROM embeddings
         WHERE document_id = ?
         ORDER BY id DESC
         LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    return dict(row) if row else {}


def get_embedding(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, document_id, model, vector, created_at
          FROM embeddings
         WHERE document_id = ?
         ORDER BY id DESC
         LIMIT 1
        """,
        (document_id,),
    ).fetchone()
    return dict(row) if row else None


def document_exists(conn: sqlite3.Connection, doc_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM documents WHERE id = ? LIMIT 1", (doc_id,)).fetchone()
    return row is not None


def clear_embedding(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM embeddings WHERE document_id = ?", (document_id,))


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, title, html, clean_text, semantic_profile, embedding, path, created_at, updated_at
          FROM documents
         WHERE id = ?
        """,
        (doc_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    row = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM document_fts WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM embeddings WHERE document_id = ?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return True
