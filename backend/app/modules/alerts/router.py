from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles
from app.models import Alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


def serialize_alert(alert: Alert) -> dict:
    return {
        "alert_id": alert.alert_id,
        "transaction_id": alert.transaction_id,
        "decision_id": alert.decision_id,
        "level": alert.level,
        "status": alert.status,
        "assignee": alert.assignee,
        "title": alert.title,
        "detail": alert.detail,
        "trace_id": alert.trace_id,
        "created_at": alert.created_at.isoformat() if alert.created_at else "",
    }


@router.get("")
def list_alerts(
    request: Request,
    status: str | None = None,
    level: str | None = None,
    assignee: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    stmt = select(Alert)
    if status:
        stmt = stmt.where(Alert.status == status)
    if level:
        stmt = stmt.where(Alert.level == level)
    if assignee:
        stmt = stmt.where(Alert.assignee == assignee)
    limit = min(max(page_size, 1), 100)
    alerts = db.execute(stmt.order_by(Alert.created_at.desc()).offset(max(page - 1, 0) * limit).limit(limit)).scalars().all()
    return api_response([serialize_alert(alert) for alert in alerts], trace_id=trace)
