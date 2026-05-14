from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

from database.tokenizer import tokenize_for_search


MODEL_NAME = "local-jieba-keyword-sparse-v1"
MAX_PROFILE_KEYWORDS = 18
MAX_VECTOR_TERMS = 96

DOMAIN_EXPANSIONS: dict[str, list[str]] = {
    "服务器": ["服务", "主机", "实例", "节点", "pod", "kubernetes", "后端", "基础设施"],
    "挂了": ["不可用", "故障", "崩溃", "超时", "宕机", "notready", "服务", "节点"],
    "出问题": ["异常", "故障", "错误", "不可用", "下降", "告警"],
    "黑客": ["安全", "攻击", "入侵", "恶意", "漏洞", "waf", "ddos", "sql注入"],
    "攻击": ["安全", "入侵", "ddos", "sql注入", "xss", "waf", "恶意"],
    "机器学习": ["ai", "算法", "模型", "推荐", "搜索排序", "特征", "效果"],
    "模型": ["ai", "算法", "推理", "推荐", "特征", "效果", "tensorflow", "triton"],
    "推荐": ["ai", "算法", "模型", "点击率", "相关性", "效果", "ab实验"],
    "质量下降": ["效果下降", "相关性下降", "点击率", "模型", "推荐", "搜索"],
}


def build_semantic_artifacts(title: str, clean_text: str) -> tuple[str, str]:
    weighted = _weighted_terms(title, clean_text)
    vector = dict(weighted.most_common(MAX_VECTOR_TERMS))
    top_keywords = weighted.most_common(MAX_PROFILE_KEYWORDS)
    profile = {
        "model": MODEL_NAME,
        "summary": _summary(title, [term for term, _ in top_keywords[:8]]),
        "keywords": [{"term": term, "weight": round(weight, 6)} for term, weight in top_keywords],
    }
    return (
        json.dumps(profile, ensure_ascii=False, sort_keys=True),
        json.dumps(vector, ensure_ascii=False, sort_keys=True),
    )


def build_query_vector(query: str) -> dict[str, float]:
    weighted = Counter[str]()
    for token in tokenize_for_search(query):
        weighted[token] += 1.0
    lowered_query = query.lower()
    for trigger, expansions in DOMAIN_EXPANSIONS.items():
        if trigger.lower() in lowered_query:
            weighted[trigger.lower()] += 1.0
            for expansion in expansions:
                for token in tokenize_for_search(expansion):
                    weighted[token] += 0.85
    return _normalize(dict(weighted))


def load_vector(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    vector: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, (int, float)):
            vector[key] = float(value)
    return vector


def load_profile(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(weight * right.get(term, 0.0) for term, weight in left.items())
    return max(0.0, min(1.0, dot))


def _weighted_terms(title: str, clean_text: str) -> Counter[str]:
    weighted = Counter[str]()
    for token in tokenize_for_search(clean_text):
        weighted[token] += 1.0
    for token in tokenize_for_search(title):
        weighted[token] += 4.0
    for trigger, expansions in DOMAIN_EXPANSIONS.items():
        trigger_tokens = set(tokenize_for_search(trigger))
        if trigger.lower() in clean_text.lower() or trigger_tokens.intersection(weighted):
            for expansion in expansions:
                for token in tokenize_for_search(expansion):
                    weighted[token] += 0.7

    filtered = Counter[str]()
    for term, count in weighted.items():
        if _keep_term(term):
            filtered[term] = 1.0 + math.log1p(count)
    return Counter(_normalize(dict(filtered)))


def _normalize(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if norm <= 0:
        return {}
    return {key: value / norm for key, value in vector.items()}


def _summary(title: str, keywords: list[str]) -> str:
    if not keywords:
        return title
    return f"{title}: " + ", ".join(keywords)


def _keep_term(term: str) -> bool:
    if not term:
        return False
    if len(term) == 1 and not term.isascii():
        return False
    return len(term) >= 2 or term.isdigit()
