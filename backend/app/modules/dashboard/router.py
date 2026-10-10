from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles
from app.models import AgentResult, Alert, DecisionRecord, ReviewCase, RiskListItem, Transaction

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics")
def metrics(request: Request, db: Session = Depends(get_db), principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR"))):
    trace = ensure_trace_id(request)
    tx_total = db.scalar(select(func.count(Transaction.id))) or 0
    alert_total = db.scalar(select(func.count(Alert.id))) or 0
    pending_cases = db.scalar(select(func.count(ReviewCase.id)).where(ReviewCase.status != "COMPLETED")) or 0
    risk_items = db.scalar(select(func.count(RiskListItem.id)).where(RiskListItem.status == "APPROVED")) or 0
    decisions = db.execute(select(DecisionRecord.decision, func.count(DecisionRecord.id)).group_by(DecisionRecord.decision)).all()
    agents = db.execute(select(AgentResult.agent_id, func.avg(AgentResult.exec_time_ms)).group_by(AgentResult.agent_id)).all()
    alert_levels = db.execute(select(Alert.level, func.count(Alert.id)).group_by(Alert.level)).all()
    return api_response(
        {
            "kpis": {
                "transactions": tx_total,
                "alerts": alert_total,
                "pending_cases": pending_cases,
                "risk_items": risk_items,
            },
            "decision_distribution": [{"name": name, "value": value} for name, value in decisions],
            "alert_levels": [{"name": name, "value": value} for name, value in alert_levels],
            "agent_latency": [{"agent_id": agent_id, "avg_ms": round(avg_ms or 0, 2)} for agent_id, avg_ms in agents],
        },
        trace_id=trace,
    )
