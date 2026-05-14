from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ON_CALL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ON_CALL_ROOT.parent
DEFAULT_DATA_DIR = REPO_ROOT / "coding-exam" / "question-1" / "data"
MAX_READ_CHARS = 80_000


class ToolError(ValueError):
    """Raised when a model requested an invalid or unsafe tool call."""


@dataclass(frozen=True)
class ToolResult:
    name: str
    arguments: dict[str, str]
    output: str


def read_file(fname: str, *, data_dir: Path = DEFAULT_DATA_DIR, max_chars: int = MAX_READ_CHARS) -> str:
    filename = _validate_filename(fname)
    root = data_dir.resolve()
    target = (root / filename).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ToolError("readFile can only read files from the configured data directory") from exc
    if not target.is_file():
        raise ToolError(f"file not found: {filename}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n[truncated]"
    return text


def _validate_filename(value: str) -> str:
    filename = str(value or "").strip()
    if not filename:
        raise ToolError("fname is required")
    if filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise ToolError("fname must be a single filename, not a path")
    if any(char in filename for char in "*?[]{}"):
        raise ToolError("fname must not contain wildcards")
    return filename

