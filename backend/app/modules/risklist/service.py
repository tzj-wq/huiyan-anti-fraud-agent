from __future__ import annotations
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import RiskListItem
from app.modules.audit.service import write_audit


def check_risk_list(db: Session, *, list_type: str | None, value: str) -> RiskListItem | None:
    stmt = select(RiskListItem).where(RiskListItem.item_value == value, RiskListItem.status == "APPROVED")
    if list_type:
        stmt = stmt.where(RiskListItem.list_type == list_type)
    return db.execute(stmt).scalars().first()


def search_risk_lists(db: Session, keyword: str | None = None) -> list[RiskListItem]:
    stmt = select(RiskListItem)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(or_(RiskListItem.item_value.like(pattern), RiskListItem.description.like(pattern)))
    return db.execute(stmt.order_by(RiskListItem.created_at.desc())).scalars().all()


def add_risk_item(db: Session, payload: dict, trace_id: str, actor: str = "admin_01", actor_role: str = "ADMIN") -> tuple[RiskListItem, str]:
    item = RiskListItem(
        item_id=f"RL-{uuid4().hex[:10]}",
        list_type=payload["list_type"],
        item_value=payload["item_value"],
        risk_level=payload.get("risk_level", "HIGH"),
        status=payload.get("status", "APPROVED"),
        source=payload.get("source", "manual"),
        owner=payload.get("owner", "admin_01"),
        reviewer=payload.get("reviewer", "reviewer_01"),
        description=payload.get("description", ""),
    )
    db.add(item)
    audit = write_audit(
        db,
        module="基础数据",
        action="CreateRiskListItem",
        target_type="RiskListItem",
        target_id=item.item_id,
        trace_id=trace_id,
        actor=actor,
        actor_role=actor_role,
        detail={"list_type": item.list_type, "risk_level": item.risk_level},
    )
    db.flush()
    return item, audit.log_id


def serialize_risk_item(item: RiskListItem) -> dict:
    return {
        "item_id": item.item_id,
        "list_type": item.list_type,
        "item_value": item.item_value,
        "risk_level": item.risk_level,
        "status": item.status,
        "source": item.source,
        "owner": item.owner,
        "reviewer": item.reviewer,
        "description": item.description,
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }
