from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_confirm_token, require_roles
from app.models import ReviewCase
from app.modules.cases.service import (
    evidence_for_case,
    list_appealable_transactions,
    review_case,
    serialize_appeal,
    serialize_case,
    submit_appeal,
)

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseReviewRequest(BaseModel):
    case_id: str
    review_result: str
    remark: str = ""
    reviewer: str = "reviewer_01"
    confirm_token: str | None = None


class AppealRequest(BaseModel):
    transaction_id: str
    user_id: str = "U2002"
    reason: str
    materials: list[str] = Field(default_factory=list)


@router.get("")
def list_cases(
    request: Request,
    status: str | None = None,
    priority: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    stmt = select(ReviewCase)
    if status:
        stmt = stmt.where(ReviewCase.status == status)
    if priority:
        stmt = stmt.where(ReviewCase.priority == priority)
    limit = min(max(page_size, 1), 100)
    cases = db.execute(stmt.order_by(ReviewCase.created_at.desc()).offset(max(page - 1, 0) * limit).limit(limit)).scalars().all()
    return api_response([serialize_case(case) for case in cases], trace_id=trace)


@router.get("/appealable-transactions")
def appealable_transactions(
    request: Request,
    user_id: str | None = "U2002",
    limit: int = 50,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "CLIENT")),
):
    trace = ensure_trace_id(request)
    if principal.role == "CLIENT":
        user_id = principal.user_id
    return api_response(list_appealable_transactions(db, user_id=user_id, limit=limit), trace_id=trace)


@router.post("/appeals")
def create_appeal(
    request: Request,
    payload: AppealRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("CLIENT", "ADMIN")),
):
    trace = ensure_trace_id(request)
    payload_data = payload.model_dump()
    if principal.role == "CLIENT":
        payload_data["user_id"] = principal.user_id
    try:
        appeal, audit_id = submit_appeal(db, payload_data, trace, actor=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return api_response(serialize_appeal(appeal), message="申诉已提交", trace_id=trace, audit_id=audit_id)


@router.get("/{case_id}/evidence")
def get_evidence(
    request: Request,
    case_id: str,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    evidence = evidence_for_case(db, case_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="案件不存在")
    return api_response(evidence, trace_id=trace)


@router.post("/review")
def submit_review(
    request: Request,
    payload: CaseReviewRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR")),
):
    trace = ensure_trace_id(request)
    require_confirm_token(payload.confirm_token)
    try:
        case, audit_id = review_case(db, payload.model_dump(), trace, actor=principal.user_id, actor_role=principal.role)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return api_response(serialize_case(case), message="复核结论已入库", trace_id=trace, audit_id=audit_id)
