from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles
from app.modules.audit.service import write_audit
from app.modules.review_assistant.rag import ensure_index, search_cases
from app.modules.review_assistant.service import advise_review

router = APIRouter(prefix="/review-assistant", tags=["review-assistant"])


class AdviceRequest(BaseModel):
    case_id: str


@router.get("/cases/search")
def search_case_library(
    request: Request,
    q: str = "",
    top_k: int = 5,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR")),
):
    """RAG 案例库检索：按语义文本返回相似历史案件（含人工复核结论）。"""
    trace = ensure_trace_id(request)
    ensure_index(db)
    results = search_cases(q, top_k=top_k)
    return api_response({"total": len(results), "items": results}, trace_id=trace)


@router.post("/advice")
def get_review_advice(
    request: Request,
    payload: AdviceRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR")),
):
    """LangGraph 审核助手：结合证据链与相似案例生成审核建议。"""
    trace = ensure_trace_id(request)
    advice = advise_review(db, payload.case_id, trace)
    if advice is None:
        raise HTTPException(status_code=404, detail="案件不存在或尚未生成完整证据链")
    audit = write_audit(
        db,
        module="审核助手",
        action="AskAdvice",
        target_type="ReviewCase",
        target_id=payload.case_id,
        trace_id=trace,
        actor=principal.user_id,
        actor_role=principal.role,
        detail={"recommendation": advice["advice"]["recommendation"], "fallback": advice["fallback"]},
    )
    db.commit()
    return api_response(advice, message="审核建议已生成", trace_id=trace, audit_id=audit.log_id)
