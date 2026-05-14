from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

V3_ROOT = Path(__file__).resolve().parent
if str(V3_ROOT) not in sys.path:
    sys.path.insert(0, str(V3_ROOT))

from agent import run_chat
from retrieval import CandidateWeights, build_candidates
from runtime import MoonshotConfig, RuntimeErrorResponse, TokenLimitError
from server import ChatSessionStore
from tools import ToolError, read_file


class FakeRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "readFile", "arguments": '{"fname":"sop-001.html"}'},
                    }
                ],
            }
        return {"role": "assistant", "content": "根据 sop-001.html，处理步骤是扩容并观察。"}


class TokenLimitThenSuccessRuntime:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            raise TokenLimitError("Moonshot API HTTP 400: token limit exceeded")
        return {"role": "assistant", "content": "压缩上下文后回答成功。"}


class NoCandidateRuntime:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_tools = "unset"
        self.messages = []

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen_tools = tools
        self.messages = messages
        return {"role": "assistant", "content": "未找到本地 SOP 文档，建议先确认告警范围。"}


class V3Tests(unittest.TestCase):
    def test_read_file_restricts_to_single_filename_inside_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sop-001.html").write_text("ok", encoding="utf-8")
            self.assertEqual(read_file("sop-001.html", data_dir=root), "ok")
            for unsafe in ("../sop-001.html", "/tmp/sop-001.html", "nested/sop-001.html", "*.html"):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(ToolError):
                        read_file(unsafe, data_dir=root)

    def test_candidate_combined_score_filters_at_threshold(self) -> None:
        keyword = lambda query, limit: [
            {"id": "sop-001", "title": "A", "snippet": "keyword", "score": 1.0},
            {"id": "sop-002", "title": "B", "snippet": "keyword", "score": 0.8},
        ]
        semantic = lambda query, limit: [
            {"id": "sop-001", "title": "A", "snippet": "semantic", "score": 0.8},
            {"id": "sop-002", "title": "B", "snippet": "semantic", "score": 1.0},
            {"id": "sop-003", "title": "C", "snippet": "semantic", "score": 0.89},
        ]
        candidates = build_candidates(
            query="oom",
            weights=CandidateWeights(keyword=0.5, semantic=0.5),
            db_path=Path("unused.sqlite3"),
            keyword_search=keyword,
            semantic_search=semantic,
        )
        self.assertEqual({item["id"] for item in candidates}, {"sop-001", "sop-002"})
        self.assertEqual([item["combined_score"] for item in candidates], [0.9, 0.9])

    def test_missing_api_key_errors_before_network(self) -> None:
        old_key = os.environ.pop("MOONSHOT_API_KEY", None)
        old_kimi_key = os.environ.pop("KIMI_API_KEY", None)
        old_kimi_lower_key = os.environ.pop("kimi_api_key", None)
        old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaises(RuntimeErrorResponse):
                MoonshotConfig.from_env()
        finally:
            if old_key is not None:
                os.environ["MOONSHOT_API_KEY"] = old_key
            if old_kimi_key is not None:
                os.environ["KIMI_API_KEY"] = old_kimi_key
            if old_kimi_lower_key is not None:
                os.environ["kimi_api_key"] = old_kimi_lower_key
            if old_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = old_openai_key

    def test_lowercase_kimi_api_key_is_accepted(self) -> None:
        old_key = os.environ.pop("MOONSHOT_API_KEY", None)
        old_kimi_key = os.environ.pop("KIMI_API_KEY", None)
        old_kimi_lower_key = os.environ.pop("kimi_api_key", None)
        old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            os.environ["kimi_api_key"] = "dummy-kimi-key"
            cfg = MoonshotConfig.from_env()
            self.assertEqual(cfg.api_key, "dummy-kimi-key")
        finally:
            os.environ.pop("kimi_api_key", None)
            if old_key is not None:
                os.environ["MOONSHOT_API_KEY"] = old_key
            if old_kimi_key is not None:
                os.environ["KIMI_API_KEY"] = old_kimi_key
            if old_kimi_lower_key is not None:
                os.environ["kimi_api_key"] = old_kimi_lower_key
            if old_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = old_openai_key

    def test_default_model_is_kimi_k26(self) -> None:
        old_key = os.environ.pop("MOONSHOT_API_KEY", None)
        old_kimi_key = os.environ.pop("KIMI_API_KEY", None)
        old_kimi_lower_key = os.environ.pop("kimi_api_key", None)
        old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
        old_model = os.environ.pop("MOONSHOT_MODEL", None)
        old_openai_model = os.environ.pop("OPENAI_MODEL", None)
        old_max_tokens = os.environ.pop("MOONSHOT_MAX_TOKENS", None)
        old_openai_max_tokens = os.environ.pop("OPENAI_MAX_TOKENS", None)
        try:
            os.environ["kimi_api_key"] = "dummy-kimi-key"
            cfg = MoonshotConfig.from_env()
            self.assertEqual(cfg.model, "kimi-k2.6")
            self.assertEqual(cfg.max_tokens, 30000)
        finally:
            os.environ.pop("kimi_api_key", None)
            if old_key is not None:
                os.environ["MOONSHOT_API_KEY"] = old_key
            if old_kimi_key is not None:
                os.environ["KIMI_API_KEY"] = old_kimi_key
            if old_kimi_lower_key is not None:
                os.environ["kimi_api_key"] = old_kimi_lower_key
            if old_openai_key is not None:
                os.environ["OPENAI_API_KEY"] = old_openai_key
            if old_model is not None:
                os.environ["MOONSHOT_MODEL"] = old_model
            if old_openai_model is not None:
                os.environ["OPENAI_MODEL"] = old_openai_model
            if old_max_tokens is not None:
                os.environ["MOONSHOT_MAX_TOKENS"] = old_max_tokens
            if old_openai_max_tokens is not None:
                os.environ["OPENAI_MAX_TOKENS"] = old_openai_max_tokens

    def test_tool_call_loop_is_testable_with_mock_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sop-001.html").write_text("<html>扩容并观察</html>", encoding="utf-8")
            result = run_chat(
                message="OOM 怎么处理",
                history=[{"role": "user", "content": "之前的问题"}],
                weights=CandidateWeights(),
                db_path=Path("unused.sqlite3"),
                data_dir=root,
                runtime=FakeRuntime(),
                keyword_search=lambda query, limit: [
                    {"id": "sop-001", "title": "OOM", "snippet": "扩容", "score": 1.0}
                ],
                semantic_search=lambda query, limit: [
                    {"id": "sop-001", "title": "OOM", "snippet": "观察", "score": 1.0}
                ],
            )
        self.assertIn("扩容", result["answer"])
        self.assertEqual(result["candidates"][0]["filename"], "sop-001.html")
        tool_steps = [step for step in result["steps"] if step["type"] == "tool"]
        self.assertEqual(len(tool_steps), 1)
        self.assertTrue(tool_steps[0]["ok"])

    def test_token_limit_error_compacts_context_and_retries_once(self) -> None:
        runtime = TokenLimitThenSuccessRuntime()
        result = run_chat(
            message="OOM 怎么处理",
            history=[{"role": "user", "content": "很长的历史" * 2000}],
            weights=CandidateWeights(),
            db_path=Path("unused.sqlite3"),
            runtime=runtime,
            keyword_search=lambda query, limit: [
                {"id": "sop-001", "title": "OOM", "snippet": "扩容", "score": 1.0}
            ],
            semantic_search=lambda query, limit: [
                {"id": "sop-001", "title": "OOM", "snippet": "观察", "score": 1.0}
            ],
        )
        self.assertEqual(runtime.calls, 2)
        self.assertIn("成功", result["answer"])

    def test_session_store_evicts_oldest_when_capacity_is_reached(self) -> None:
        store = ChatSessionStore(max_sessions=1)
        first = store.create({"message": "first"})
        second = store.create({"message": "second"})
        self.assertIsNone(store.pop(first))
        self.assertEqual(store.pop(second), {"message": "second"})

    def test_empty_retrieval_still_calls_runtime_without_tools(self) -> None:
        runtime = NoCandidateRuntime()
        result = run_chat(
            message="没有文档命中的问题",
            history=[],
            weights=CandidateWeights(),
            db_path=Path("unused.sqlite3"),
            runtime=runtime,
            keyword_search=lambda query, limit: [],
            semantic_search=lambda query, limit: [],
        )
        self.assertEqual(runtime.calls, 1)
        self.assertIsNone(runtime.seen_tools)
        self.assertEqual(result["candidates"], [])
        self.assertIn("未找到", result["answer"])
        self.assertTrue(any("No document reached" in item.get("content", "") for item in runtime.messages))


if __name__ == "__main__":
    unittest.main()
