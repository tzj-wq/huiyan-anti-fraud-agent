"""LangGraph 审核助手：读取案件证据链 → RAG 检索相似案例 → LLM 综合生成审核建议。

状态图（StateGraph）：
    START → read_case → retrieve → advise → END

节点均为无状态工厂函数（依赖在 service 层注入），图可编译为单例复用；
LLM 不可用/失败/输出不可解析时 advise 节点回退规则模板并置 fallback=True。
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.llm import LLMClient
from app.modules.review_assistant.rag import search_cases

TOP_K_CANDIDATES = 3


class ReviewState(TypedDict):
    case_id: str
    case_evidence: dict
    candidates: list[dict]
    advice: dict
    fallback: bool


def _make_retrieve() -> Callable[[ReviewState], dict]:
    """从案件证据链构造检索文本，RAG 检索 top-k 相似案例。"""

    def retrieve(state: ReviewState) -> dict:
        evidence = state["case_evidence"]
        case = evidence.get("case", {})
        transaction = case.get("transaction", {})
        decision = case.get("decision", {})
        appeal = case.get("appeal") or {}
        query_parts = [
            transaction.get("user_id", ""),
            str(transaction.get("amount", "")),
            transaction.get("channel", ""),
            transaction.get("location", ""),
            transaction.get("counterparty_type", ""),
            decision.get("decision", ""),
            "、".join(decision.get("risk_labels") or []),
            decision.get("evidence_summary", ""),
            appeal.get("reason", ""),
        ]
        query_text = " ".join(part for part in query_parts if part)
        return {"candidates": search_cases(query_text, top_k=TOP_K_CANDIDATES)}

    return retrieve


def _make_advise(llm_client: LLMClient) -> Callable[[ReviewState], dict]:
    """LLM 综合证据链与相似案例生成审核建议；失败回退规则模板。"""

    def advise(state: ReviewState) -> dict:
        candidates = state["candidates"]
        result = llm_client.generate_review_advice(case_evidence=state["case_evidence"], candidates=candidates)
        if result is None:
            return {"advice": _fallback_advice(state["case_evidence"], candidates), "fallback": True}
        return {"advice": result, "fallback": False}

    return advise


def _fallback_advice(case_evidence: dict, candidates: list[dict]) -> dict:
    """规则基线审核建议：LLM 不可用时保证审核助手仍可输出可执行建议。"""
    decision = (case_evidence.get("case") or {}).get("decision", {})
    risk_score = float(decision.get("risk_score") or 0)
    conflict = bool(decision.get("conflict_flag"))
    original_decision = decision.get("decision", "")
    if risk_score >= 0.85 or original_decision == "BLOCK":
        recommendation = "REVIEW_CONFIRM"
        confidence = 0.8
    elif risk_score >= 0.6:
        recommendation = "ESCALATE" if conflict else "REVIEW_CONFIRM"
        confidence = 0.6
    else:
        recommendation = "RELEASE"
        confidence = 0.5
    rationale = (
        f"规则基线：风险分 {risk_score:.2f}"
        f"{'，且存在 Agent 冲突' if conflict else ''}，"
        f"LLM 综合不可用，建议人工按 {recommendation} 动作处理。"
    )
    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "rationale": rationale,
        "cited_cases": [item["case_id"] for item in candidates[:2]],
    }


def build_review_graph(llm_client: LLMClient | None = None):
    """构建并编译审核助手状态图（无外部 session 依赖，可复用单例）。"""
    graph = StateGraph(ReviewState)
    graph.add_node("read_case", lambda state: state)
    graph.add_node("retrieve", _make_retrieve())
    graph.add_node("advise", _make_advise(llm_client or LLMClient()))
    graph.add_edge(START, "read_case")
    graph.add_edge("read_case", "retrieve")
    graph.add_edge("retrieve", "advise")
    graph.add_edge("advise", END)
    return graph.compile()
