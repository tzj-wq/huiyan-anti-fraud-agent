from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_confirm_token, require_roles
from app.modules.risklist.service import add_risk_item, check_risk_list, search_risk_lists, serialize_risk_item

router = APIRouter(prefix="/risklist", tags=["risklist"])


class RiskItemRequest(BaseModel):
    list_type: str
    item_value: str
    risk_level: str = "HIGH"
    description: str = ""
    confirm_token: str | None = None


@router.get("/check")
def check(
    request: Request,
    value: str,
    list_type: str | None = None,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR", "CLIENT")),
):
    trace = ensure_trace_id(request)
    item = check_risk_list(db, list_type=list_type, value=value)
    return api_response(
        {"hit": bool(item), "item": serialize_risk_item(item) if item else None},
        trace_id=trace,
    )


@router.get("")
def list_items(
    request: Request,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    return api_response([serialize_risk_item(item) for item in search_risk_lists(db, keyword)], trace_id=trace)


@router.post("")
def create_item(
    request: Request,
    payload: RiskItemRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN")),
):
    trace = ensure_trace_id(request)
    require_confirm_token(payload.confirm_token)
    item, audit_id = add_risk_item(db, payload.model_dump(), trace, actor=principal.user_id, actor_role=principal.role)
    db.commit()
    return api_response(serialize_risk_item(item), message="名单项已创建", trace_id=trace, audit_id=audit_id)
