from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles
from app.models import Transaction
from app.modules.detection.service import detect_transaction, get_decision_process, list_transactions

router = APIRouter(prefix="/detect", tags=["detection"])


class TransactionPayload(BaseModel):
    transaction: dict
    context: dict | None = None


@router.post("/transaction")
def detect(
    request: Request,
    payload: TransactionPayload,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "CLIENT")),
):
    trace = ensure_trace_id(request)
    transaction = payload.transaction | {"context": payload.context or {}}
    if principal.role == "CLIENT":
        transaction["user_id"] = principal.user_id
    data = detect_transaction(db, transaction, trace)
    return api_response(data, trace_id=trace)


@router.get("/transactions")
def transactions(
    request: Request,
    keyword: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR", "CLIENT")),
):
    trace = ensure_trace_id(request)
    user_id = principal.user_id if principal.role == "CLIENT" else None
    return api_response(list_transactions(db, keyword=keyword, limit=limit, user_id=user_id), trace_id=trace)


@router.get("/decisions/{transaction_id}/process")
def decision_process(
    request: Request,
    transaction_id: str,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR", "CLIENT")),
):
    trace = ensure_trace_id(request)
    transaction = db.execute(select(Transaction).where(Transaction.transaction_id == transaction_id)).scalars().first()
    if not transaction:
        raise HTTPException(status_code=404, detail="交易不存在")
    if principal.role == "CLIENT" and transaction.user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="无权查看该交易的决策过程")
    process = get_decision_process(db, transaction_id)
    if not process:
        return api_response(None, message="该交易暂无协同决策过程记录", trace_id=trace)
    return api_response(process, trace_id=trace)
