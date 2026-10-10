from __future__ import annotations
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles
from app.modules.audit.service import audit_query, build_audit_workbook, serialize_audit, write_audit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
def list_audit_logs(
    request: Request,
    trace_id: str | None = None,
    actor: str | None = None,
    module: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    limit = min(max(page_size, 1), 100)
    offset = max(page - 1, 0) * limit
    stmt = audit_query(trace_id=trace_id, actor=actor, module=module, start_at=start_at, end_at=end_at)
    logs = db.execute(stmt.offset(offset).limit(limit)).scalars().all()
    return api_response([serialize_audit(log) for log in logs], trace_id=trace)


@router.get("/logs/export")
def export_audit_logs(
    request: Request,
    trace_id: str | None = None,
    actor: str | None = None,
    module: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN", "AUDITOR")),
):
    trace = ensure_trace_id(request)
    stmt = audit_query(trace_id=trace_id, actor=actor, module=module, start_at=start_at, end_at=end_at)
    logs = db.execute(stmt.limit(5000)).scalars().all()
    audit = write_audit(
        db,
        module="审计日志",
        action="Export",
        target_type="AuditLog",
        target_id="xlsx",
        trace_id=trace,
        actor=principal.user_id,
        actor_role=principal.role,
        detail={"filters": {"trace_id": trace_id, "actor": actor, "module": module}},
    )
    db.commit()
    stream = build_audit_workbook(logs)
    headers = {"Content-Disposition": 'attachment; filename="huiyan-audit-logs.xlsx"', "X-Audit-ID": audit.log_id}
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
