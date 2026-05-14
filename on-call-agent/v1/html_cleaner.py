from __future__ import annotations

import re
from html.parser import HTMLParser


class DocumentHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "main", "header", "footer", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "main", "header", "footer", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)


def _normalize_text(value: str) -> str:
    lines = []
    for line in value.replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def clean_html(html: str) -> tuple[str, str]:
    parser = DocumentHTMLParser()
    parser.feed(html)
    parser.close()
    title = _normalize_text(" ".join(parser._title_parts))
    clean_text = _normalize_text("\n".join(parser._text_parts))
    if not title:
        first_line = clean_text.splitlines()[0] if clean_text else "Untitled document"
        title = first_line[:120]
    return title, clean_text

