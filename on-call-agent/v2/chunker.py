from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag


HEADING_RE = re.compile(r"^h[1-6]$")
SKIP_TAGS = {"script", "style", "noscript"}
MIN_CHUNK_CHARS = 10


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    chunk_index: int
    heading: str
    heading_path: str
    chunk_text: str


def build_chunks(html: str, *, title: str, doc_id: str) -> list[ChunkRecord]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(list(SKIP_TAGS)):
        tag.decompose()

    body = soup.body or soup
    headings = [
        node
        for node in body.find_all(True)
        if isinstance(node, Tag) and node.name and HEADING_RE.fullmatch(node.name)
    ]

    if not headings:
        fallback = _normalize_text(body.get_text(" ", strip=True))
        if len(fallback) < MIN_CHUNK_CHARS:
            return []
        return [
            ChunkRecord(
                chunk_id=f"{doc_id}::0000",
                chunk_index=0,
                heading=title,
                heading_path=title,
                chunk_text=fallback,
            )
        ]

    chunks: list[ChunkRecord] = []
    heading_stack: list[str] = []
    chunk_index = 0

    for heading_node in headings:
        heading_text = _normalize_text(heading_node.get_text(" ", strip=True))
        if not heading_text:
            continue

        level = int(heading_node.name[1])
        heading_stack = heading_stack[: max(0, level - 1)]
        heading_stack.append(heading_text)
        heading_path = " / ".join(heading_stack)

        content_parts: list[str] = []
        for sibling in heading_node.next_siblings:
            if isinstance(sibling, Tag) and sibling.name and HEADING_RE.fullmatch(sibling.name):
                sibling_level = int(sibling.name[1])
                if sibling_level <= level:
                    break
            text = _sibling_text(sibling)
            if text:
                content_parts.append(text)

        content = _normalize_text("\n".join(content_parts))
        chunk_text = _normalize_text("\n".join(filter(None, [heading_path, content])))
        if len(chunk_text) < MIN_CHUNK_CHARS:
            continue

        chunks.append(
            ChunkRecord(
                chunk_id=f"{doc_id}::{chunk_index:04d}",
                chunk_index=chunk_index,
                heading=heading_text,
                heading_path=heading_path,
                chunk_text=chunk_text,
            )
        )
        chunk_index += 1

    return chunks


def _sibling_text(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return _normalize_text(str(node))
    if isinstance(node, Tag):
        if node.name and node.name.lower() in SKIP_TAGS:
            return ""
        return _normalize_text(node.get_text(" ", strip=True))
    return ""


def _normalize_text(value: str) -> str:
    lines = []
    for line in value.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)
