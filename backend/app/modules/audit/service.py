from __future__ import annotations
from datetime import datetime
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import AuditLog


def write_audit(
    db: Session,
    *,
    module: str,
    action: str,
    target_type: str,
    target_id: str,
    trace_id: str,
    actor: str = "admin_01",
    actor_role: str = "ADMIN",
    result: str = "SUCCESS",
    detail: dict | None = None,
) -> AuditLog:
    log = AuditLog(
        log_id=f"AUD-{uuid4().hex[:12]}",
        actor=actor,
        actor_role=actor_role,
        action=action,
        module=module,
        target_type=target_type,
        target_id=target_id,
        result=result,
        detail=detail or {},
        trace_id=trace_id,
    )
    db.add(log)
    db.flush()
    return log


def audit_query(
    *,
    trace_id: str | None = None,
    actor: str | None = None,
    module: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> Select[tuple[AuditLog]]:
    stmt = select(AuditLog)
    if trace_id:
        stmt = stmt.where(AuditLog.trace_id == trace_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if start_at:
        stmt = stmt.where(AuditLog.created_at >= start_at)
    if end_at:
        stmt = stmt.where(AuditLog.created_at <= end_at)
    return stmt.order_by(AuditLog.created_at.desc())


def serialize_audit(log: AuditLog) -> dict:
    return {
        "log_id": log.log_id,
        "time": log.created_at.isoformat() if log.created_at else "",
        "actor": log.actor,
        "actor_role": log.actor_role,
        "module": log.module,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "result": log.result,
        "trace_id": log.trace_id,
        "detail": log.detail,
    }


def build_audit_workbook(logs: list[AuditLog]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Audit Logs"
    headers = ["时间", "操作者", "角色", "模块", "动作", "目标对象", "结果", "TraceID", "详情"]
    sheet.append(headers)
    for log in logs:
        sheet.append(
            [
                log.created_at.isoformat() if log.created_at else "",
                log.actor,
                log.actor_role,
                log.module,
                log.action,
                f"{log.target_type}:{log.target_id}",
                log.result,
                log.trace_id,
                str(log.detail),
            ]
        )
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 48)
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream
