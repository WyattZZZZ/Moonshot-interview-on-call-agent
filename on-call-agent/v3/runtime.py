from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "kimi-k2.6"
DEFAULT_MAX_TOKENS = 30000
DEFAULT_TEMPERATURE = 1.0


class RuntimeErrorResponse(RuntimeError):
    pass


class ChatRuntime(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class MoonshotConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE

    @classmethod
    def from_env(cls) -> "MoonshotConfig":
        api_key = (
            os.environ.get("MOONSHOT_API_KEY")
            or os.environ.get("KIMI_API_KEY")
            or os.environ.get("kimi_api_key")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        if not api_key:
            raise RuntimeErrorResponse("MOONSHOT_API_KEY, KIMI_API_KEY, or kimi_api_key is required for v3 runtime")
        return cls(
            api_key=api_key,
            base_url=(os.environ.get("MOONSHOT_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            model=os.environ.get("MOONSHOT_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL,
            max_tokens=_env_int("MOONSHOT_MAX_TOKENS", _env_int("OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
            temperature=_env_float("MOONSHOT_TEMPERATURE", _env_float("OPENAI_TEMPERATURE", DEFAULT_TEMPERATURE)),
        )


class MoonshotChatRuntime:
    def __init__(self, config: MoonshotConfig | None = None, *, timeout: float = 60.0) -> None:
        self.config = config or MoonshotConfig.from_env()
        self.timeout = timeout

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeErrorResponse(f"Moonshot API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeErrorResponse(f"Moonshot API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeErrorResponse("Moonshot API returned invalid JSON") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeErrorResponse("Moonshot API returned no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeErrorResponse("Moonshot API returned an invalid message")
        return message


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "readFile",
        "description": "Read one candidate SOP file by filename. The filename must come from the provided candidate list.",
        "parameters": {
            "type": "object",
            "properties": {
                "fname": {
                    "type": "string",
                    "description": "A single filename such as sop-001.html. Do not include a path.",
                }
            },
            "required": ["fname"],
            "additionalProperties": False,
        },
    },
}
