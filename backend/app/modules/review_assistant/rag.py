"""RAG 案例库：基于 TF-IDF（char_wb 2-3 gram）与余弦相似度的历史案件检索。

案例文档由交易画像、风险标签、Agent 证据摘要、申诉文本与人工复核结论拼接而成；
案件复核完成（COMPLETED）后自动增量入库（见 cases.service.review_case），
查询时按相似度返回 top-k 历史案例，供 LLM 审核助手做检索增强生成。
"""
from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentResult, FeedbackSample, ReviewCase, Transaction

MIN_SIMILARITY = 0.05


class CaseIndex:
    """内存案例索引：TF-IDF 向量化 + 余弦相似度 top-k 检索。"""

    def __init__(self) -> None:
        self._docs: dict[str, str] = {}
        self._meta: dict[str, dict] = {}
        self._doc_ids: list[str] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None

    def reset(self) -> None:
        self._docs.clear()
        self._meta.clear()
        self._doc_ids.clear()
        self._vectorizer = None
        self._matrix = None

    def _rebuild(self) -> None:
        self._doc_ids = list(self._docs.keys())
        if not self._doc_ids:
            self._vectorizer = None
            self._matrix = None
            return
        self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
        self._matrix = self._vectorizer.fit_transform([self._docs[case_id] for case_id in self._doc_ids])

    def upsert(self, case_id: str, document: str, meta: dict) -> None:
        self._docs[case_id] = document
        self._meta[case_id] = meta
        self._rebuild()

    def search(self, query_text: str, top_k: int = 5) -> list[dict]:
        if not self._doc_ids or not query_text.strip():
            return []
        query_vec = self._vectorizer.transform([query_text])
        similarities = cosine_similarity(query_vec, self._matrix)[0]
        ranked = sorted(zip(self._doc_ids, similarities), key=lambda item: item[1], reverse=True)
        results: list[dict] = []
        for case_id, score in ranked[: max(1, min(top_k, 20))]:
            if score < MIN_SIMILARITY:
                continue
            results.append({**self._meta[case_id], "similarity": round(float(score), 4)})
        return results

    def size(self) -> int:
        return len(self._doc_ids)


def build_case_document(db: Session, case_id: str) -> tuple[str, dict] | None:
    """构建案例检索文档与元数据；案件尚未完成人工复核（无 FeedbackSample）时返回 None。"""
    sample = db.execute(select(FeedbackSample).where(FeedbackSample.case_id == case_id)).scalars().first()
    case = db.execute(select(ReviewCase).where(ReviewCase.case_id == case_id)).scalars().first()
    if not sample or not case:
        return None
    transaction = db.execute(select(Transaction).where(Transaction.transaction_id == sample.transaction_id)).scalars().first()
    decision = transaction.decision if transaction else None
    appeal = case.appeal
    raw_payload = (transaction.raw_payload if transaction else {}) or {}
    agent_lines: list[str] = []
    results = db.execute(select(AgentResult).where(AgentResult.transaction_id == sample.transaction_id)).scalars().all()
    for result in results:
        if result.degraded:
            continue
        top_evidence = ""
        if result.evidence_list:
            first = result.evidence_list[0]
            top_evidence = first.get("summary", "") if isinstance(first, dict) else str(first)
        agent_lines.append(f"{result.agent_id} {result.risk_label} {result.risk_score:.2f} {top_evidence}")
    parts = [
        f"用户 {transaction.user_id if transaction else ''}",
        f"金额 {transaction.amount if transaction else 0:.2f}",
        f"渠道 {transaction.channel if transaction else ''}",
        f"设备 {transaction.device_id if transaction else ''}",
        f"地点 {transaction.location if transaction else ''}",
        f"交易对象 {raw_payload.get('counterparty_type', '')}",
        f"决策 {decision.decision if decision else ''}",
        f"风险分 {decision.risk_score if decision else 0:.2f}",
        f"风险标签 {'、'.join(decision.risk_labels or []) if decision else ''}",
        f"证据摘要 {decision.evidence_summary if decision else ''}",
    ]
    if agent_lines:
        parts.append("Agent证据 " + "；".join(agent_lines))
    if appeal:
        parts.append(f"申诉 {appeal.reason}")
        if appeal.materials:
            parts.append("申诉材料 " + "、".join(appeal.materials))
    parts.append(f"复核结论 {case.review_result}")
    parts.append(f"复核标签 {sample.label}")
    document = " ".join(part for part in parts if part)
    meta = {
        "case_id": case_id,
        "transaction_id": sample.transaction_id,
        "user_id": transaction.user_id if transaction else "",
        "amount": transaction.amount if transaction else 0,
        "channel": transaction.channel if transaction else "",
        "device_id": transaction.device_id if transaction else "",
        "location": transaction.location if transaction else "",
        "decision": decision.decision if decision else "",
        "risk_score": decision.risk_score if decision else 0,
        "risk_labels": decision.risk_labels or [],
        "review_result": case.review_result,
        "label": sample.label,
        "created_at": case.created_at.isoformat() if case.created_at else "",
    }
    return document, meta


_index = CaseIndex()


def ensure_index(db: Session) -> int:
    """全量重建案例索引（幂等），返回索引条数。"""
    case_ids = list(db.execute(select(FeedbackSample.case_id).distinct()).scalars().all())
    _index.reset()
    for case_id in case_ids:
        built = build_case_document(db, case_id)
        if built:
            _index.upsert(case_id, built[0], built[1])
    return _index.size()


def index_case(db: Session, case_id: str) -> bool:
    """单案例增量入库；案件无复核样本时返回 False。"""
    built = build_case_document(db, case_id)
    if not built:
        return False
    _index.upsert(case_id, built[0], built[1])
    return True


def search_cases(query_text: str, top_k: int = 5) -> list[dict]:
    """按文本相似度检索历史案例，返回带 similarity 的 top-k 列表。"""
    return _index.search(query_text, top_k)
