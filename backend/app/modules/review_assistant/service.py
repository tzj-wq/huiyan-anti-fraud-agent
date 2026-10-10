"""审核助手服务层：组装 LangGraph 图执行审核建议工作流。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.llm import LLMClient
from app.modules.cases.service import evidence_for_case
from app.modules.review_assistant.graph import build_review_graph
from app.modules.review_assistant.rag import ensure_index

_REVIEW_GRAPH = None


def _graph():
    global _REVIEW_GRAPH
    if _REVIEW_GRAPH is None:
        _REVIEW_GRAPH = build_review_graph()
    return _REVIEW_GRAPH


def advise_review(db: Session, case_id: str, trace_id: str) -> dict | None:
    """对指定案件生成审核建议（LangGraph：证据链 → RAG 检索 → LLM/规则建议）。

    案件不存在或证据链缺失时返回 None。
    """
    case_evidence = evidence_for_case(db, case_id)
    if not case_evidence:
        return None
    ensure_index(db)
    state = {
        "case_id": case_id,
        "case_evidence": case_evidence,
        "candidates": [],
        "advice": {},
        "fallback": False,
    }
    result = _graph().invoke(state, config={"recursion_limit": 20})
    return {
        "case_id": case_id,
        "advice": result["advice"],
        "candidates": result["candidates"],
        "fallback": bool(result["fallback"]),
        "llm": LLMClient().status(),
        "trace_id": trace_id,
    }
