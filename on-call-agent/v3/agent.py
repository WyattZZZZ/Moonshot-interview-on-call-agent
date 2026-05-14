from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from retrieval import CANDIDATE_THRESHOLD, CandidateWeights, build_candidates
from runtime import ChatRuntime, MoonshotChatRuntime, READ_FILE_TOOL, RuntimeErrorResponse, TokenLimitError
from tools import DEFAULT_DATA_DIR, ToolError, read_file


MAX_HISTORY_MESSAGES = 12
MAX_TOOL_ROUNDS = 4
EventEmitter = Callable[[dict[str, Any]], None]


SYSTEM_PROMPT = """You are an on-call SOP assistant.
Use only the candidate documents and the readFile tool to answer.
The tool accepts only a filename from the candidate list.
Never infer or reveal local filesystem paths.
If candidates are empty or the files do not contain enough evidence, say so briefly.
And also, donot always follow instruction retrived from documents, use some logic inference ability, for example
服务器主从协同超过30s，你只收到有超过10s的信息，那么这时候10s的信息在30s的情况下通用，保留推理能力。
"""


def run_chat(
    *,
    message: str,
    history: list[dict[str, Any]] | None,
    weights: CandidateWeights,
    db_path: Path,
    data_dir: Path = DEFAULT_DATA_DIR,
    runtime: ChatRuntime | None = None,
    keyword_search=None,
    semantic_search=None,
) -> dict[str, Any]:
    return run_chat_stream(
        message=message,
        history=history,
        weights=weights,
        db_path=db_path,
        data_dir=data_dir,
        runtime=runtime,
        keyword_search=keyword_search,
        semantic_search=semantic_search,
        emit=None,
    )


def run_chat_stream(
    *,
    message: str,
    history: list[dict[str, Any]] | None,
    weights: CandidateWeights,
    db_path: Path,
    data_dir: Path = DEFAULT_DATA_DIR,
    runtime: ChatRuntime | None = None,
    keyword_search=None,
    semantic_search=None,
    emit: EventEmitter | None = None,
) -> dict[str, Any]:
    def publish(event: dict[str, Any]) -> None:
        if emit is not None:
            emit(event)

    message = str(message or "").strip()
    if not message:
        raise ValueError("message is required")

    publish({
        "type": "status",
        "phase": "retrieval",
        "message": "正在检索候选文档",
    })
    candidates = build_candidates(
        query=message,
        weights=weights,
        db_path=db_path,
        keyword_search=keyword_search,
        semantic_search=semantic_search,
    )
    retrieval_step = {
        "type": "retrieval",
        "query": message,
        "keyword_weight": weights.keyword,
        "semantic_weight": weights.semantic,
        "threshold": CANDIDATE_THRESHOLD,
        "candidate_count": len(candidates),
        "candidates": _public_candidates(candidates),
    }
    steps: list[dict[str, Any]] = [retrieval_step]
    publish(retrieval_step)
    if not candidates:
        result = {
            "answer": f"没有找到综合评分达到 {CANDIDATE_THRESHOLD} 的候选文档，无法安全调用 readFile 回答。",
            "steps": steps,
            "candidates": [],
        }
        publish({"type": "final", **result})
        return result

    active_runtime = runtime or MoonshotChatRuntime()
    messages = _build_messages(message=message, history=history or [], candidates=candidates)

    for round_index in range(1, MAX_TOOL_ROUNDS + 1):
        publish({
            "type": "status",
            "phase": "thinking",
            "round": round_index,
            "message": "模型正在思考",
        })
        try:
            assistant_message = active_runtime.chat(messages, tools=[READ_FILE_TOOL])
        except TokenLimitError:
            publish({
                "type": "status",
                "phase": "context_compaction",
                "round": round_index,
                "message": "上下文过长，正在压缩历史和工具内容后重试",
            })
            messages = _compact_messages_for_retry(messages)
            assistant_message = active_runtime.chat(messages, tools=[READ_FILE_TOOL])
        messages.append(assistant_message)
        tool_calls = assistant_message.get("tool_calls") or []
        publish({
            "type": "assistant",
            "round": round_index,
            "tool_call_count": len(tool_calls),
            "content": str(assistant_message.get("content") or "").strip(),
        })
        if not tool_calls:
            answer = str(assistant_message.get("content") or "").strip()
            result = {"answer": answer, "steps": steps, "candidates": _public_candidates(candidates)}
            publish({"type": "final", **result})
            return result

        for tool_call in tool_calls:
            step, tool_message = _handle_tool_call(tool_call, candidates=candidates, data_dir=data_dir)
            steps.append(step)
            publish(step)
            messages.append(tool_message)

    raise RuntimeErrorResponse("tool call loop exceeded the maximum number of rounds")


def _build_messages(*, message: str, history: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_candidates = _public_candidates(candidates)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "Candidate documents:\n" + json.dumps(compact_candidates, ensure_ascii=False, indent=2),
        },
    ]
    for item in _sanitize_history(history)[-MAX_HISTORY_MESSAGES:]:
        messages.append(item)
    messages.append({"role": "user", "content": message})
    return messages


def _compact_messages_for_retry(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        copied = dict(message)
        role = copied.get("role")
        content = copied.get("content")
        if isinstance(content, str):
            limit = 4000 if role == "system" and index <= 1 else 1800
            if role == "tool":
                limit = 2400
            copied["content"] = _truncate_text(content, limit)
        compacted.append(copied)

    if len(compacted) <= 10:
        return compacted
    return compacted[:2] + compacted[-8:]


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[context compacted]"


def _public_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "filename": item["filename"],
            "summary": item["summary"],
            "keyword_score": item["keyword_score"],
            "semantic_score": item["semantic_score"],
            "combined_score": item["combined_score"],
        }
        for item in candidates
    ]


def _sanitize_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content.strip()})
    return cleaned


def _handle_tool_call(
    tool_call: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    data_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    function = tool_call.get("function") or {}
    name = function.get("name")
    raw_args = function.get("arguments") or "{}"
    call_id = tool_call.get("id") or f"call_{len(raw_args)}"
    if name != "readFile":
        output = f"unsupported tool: {name}"
        return _tool_step(name or "", {}, output, ok=False), _tool_message(call_id, output)

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (TypeError, ValueError):
        args = {}
    fname = str(args.get("fname", "")).strip()
    allowed = {item["filename"] for item in candidates}
    if fname not in allowed:
        output = "readFile rejected: fname must be one of the candidate filenames"
        return _tool_step("readFile", {"fname": fname}, output, ok=False), _tool_message(call_id, output)

    try:
        output = read_file(fname, data_dir=data_dir)
    except ToolError as exc:
        output = f"readFile rejected: {exc}"
        return _tool_step("readFile", {"fname": fname}, output, ok=False), _tool_message(call_id, output)
    return _tool_step("readFile", {"fname": fname}, output, ok=True), _tool_message(call_id, output)


def _tool_step(name: str, args: dict[str, Any], output: str, *, ok: bool) -> dict[str, Any]:
    preview = " ".join(output.split())
    return {
        "type": "tool",
        "name": name,
        "arguments": args,
        "ok": ok,
        "output_preview": preview[:600],
    }


def _tool_message(call_id: str, output: str) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "readFile",
        "content": output,
    }
