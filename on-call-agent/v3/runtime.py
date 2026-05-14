from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
DEFAULT_MODEL = "kimi-k2.6"
DEFAULT_MAX_TOKENS = 30000
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 0.75
DEFAULT_RETRY_MAX_SECONDS = 8.0
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


class RuntimeErrorResponse(RuntimeError):
    pass


class TokenLimitError(RuntimeErrorResponse):
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
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS
    retry_max_seconds: float = DEFAULT_RETRY_MAX_SECONDS

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
            max_retries=_env_int("MOONSHOT_MAX_RETRIES", _env_int("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
            retry_base_seconds=_env_float("MOONSHOT_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS),
            retry_max_seconds=_env_float("MOONSHOT_RETRY_MAX_SECONDS", DEFAULT_RETRY_MAX_SECONDS),
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
        data = self._post_with_retries(req)

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeErrorResponse("Moonshot API returned no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeErrorResponse("Moonshot API returned an invalid message")
        return message

    def _post_with_retries(self, req: urllib.request.Request) -> dict[str, Any]:
        attempts = max(1, self.config.max_retries + 1)
        last_error: RuntimeErrorResponse | None = None
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                message = f"Moonshot API HTTP {exc.code}: {detail}"
                if exc.code == 400 and _looks_like_token_limit(detail):
                    raise TokenLimitError(message) from exc
                last_error = RuntimeErrorResponse(message)
                if exc.code not in RETRYABLE_HTTP_STATUSES or attempt >= attempts - 1:
                    raise last_error from exc
                _sleep_before_retry(
                    attempt,
                    self.config.retry_base_seconds,
                    self.config.retry_max_seconds,
                    exc.headers.get("Retry-After"),
                )
            except urllib.error.URLError as exc:
                last_error = RuntimeErrorResponse(f"Moonshot API request failed: {exc.reason}")
                if attempt >= attempts - 1:
                    raise last_error from exc
                _sleep_before_retry(attempt, self.config.retry_base_seconds, self.config.retry_max_seconds, None)
            except json.JSONDecodeError as exc:
                raise RuntimeErrorResponse("Moonshot API returned invalid JSON") from exc
        raise last_error or RuntimeErrorResponse("Moonshot API request failed")


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


def _looks_like_token_limit(detail: str) -> bool:
    lowered = detail.lower()
    return "token" in lowered and ("limit" in lowered or "exceeded" in lowered)


def _sleep_before_retry(attempt: int, base_seconds: float, max_seconds: float, retry_after: str | None) -> None:
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = 0.0
        if delay > 0:
            time.sleep(min(delay, max_seconds))
            return
    delay = min(max_seconds, max(0.0, base_seconds) * (2 ** attempt))
    if delay > 0:
        time.sleep(delay)


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
