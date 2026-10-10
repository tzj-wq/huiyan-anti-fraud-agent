from __future__ import annotations
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentResult, Alert, DecisionProcess, FeedbackSample, ReviewCase, Transaction, UserAppeal
from app.modules.audit.service import write_audit
from app.modules.review_assistant.rag import index_case
from app.modules.strategy.learning import record_feedback


def _timeline_event(title: str, detail: str) -> dict:
    return {"title": title, "detail": detail}


def serialize_appeal(appeal: UserAppeal | None) -> dict | None:
    if not appeal:
        return None
    return {
        "appeal_id": appeal.appeal_id,
        "case_id": appeal.case_id,
        "transaction_id": appeal.transaction_id,
        "user_id": appeal.user_id,
        "status": appeal.status,
        "reason": appeal.reason,
        "materials": appeal.materials,
        "timeline": appeal.timeline,
        "handler_note": appeal.handler_note,
        "created_at": appeal.created_at.isoformat() if appeal.created_at else "",
        "updated_at": appeal.updated_at.isoformat() if appeal.updated_at else "",
    }


def serialize_case(case: ReviewCase) -> dict:
    alert = case.alert
    decision = alert.decision if alert else None
    transaction = decision.transaction if decision else None
    raw_payload = transaction.raw_payload if transaction else {}
    return {
        "case_id": case.case_id,
        "alert_id": case.alert_id,
        "status": case.status,
        "priority": case.priority,
        "review_result": case.review_result,
        "reviewer": case.reviewer,
        "remark": case.remark,
        "trace_id": case.trace_id,
        "created_at": case.created_at.isoformat() if case.created_at else "",
        "alert": {
            "level": alert.level if alert else "",
            "title": alert.title if alert else "",
            "detail": alert.detail if alert else "",
            "status": alert.status if alert else "",
        },
        "transaction": {
            "transaction_id": transaction.transaction_id if transaction else "",
            "user_id": transaction.user_id if transaction else "",
            "amount": transaction.amount if transaction else 0,
            "channel": transaction.channel if transaction else "",
            "device_id": transaction.device_id if transaction else "",
            "counterparty_type": raw_payload.get("counterparty_type", "") if raw_payload else "",
            "location": transaction.location if transaction else "",
        },
        "decision": {
            "decision": decision.decision if decision else "",
            "risk_score": decision.risk_score if decision else 0,
            "conflict_flag": decision.conflict_flag if decision else False,
            "risk_labels": decision.risk_labels if decision else [],
            "evidence_summary": decision.evidence_summary if decision else "",
        },
        "appeal": serialize_appeal(case.appeal),
    }


def evidence_for_case(db: Session, case_id: str) -> dict | None:
    case = db.execute(select(ReviewCase).where(ReviewCase.case_id == case_id)).scalars().first()
    if not case or not case.alert or not case.alert.decision:
        return None
    tx_id = case.alert.transaction_id
    results = db.execute(select(AgentResult).where(AgentResult.transaction_id == tx_id)).scalars().all()
    process = db.execute(select(DecisionProcess).where(DecisionProcess.transaction_id == tx_id)).scalars().first()
    round1_confidence: dict[str, float] = {}
    arbitration = None
    if process and process.stages:
        rounds = process.stages.get("rounds") or []
        if rounds:
            for agent in rounds[0].get("agents", []):
                round1_confidence[agent.get("agent_id")] = agent.get("confidence")
        if len(rounds) > 1:
            arbitration = rounds[1]
    return {
        "case": serialize_case(case),
        "evidence_chain": [
            {
                "agent_id": result.agent_id,
                "agent_type": result.agent_type,
                "risk_score": result.risk_score,
                "risk_label": result.risk_label,
                "evidence": result.evidence_list,
                "exec_time_ms": result.exec_time_ms,
                "degraded": result.degraded,
                "confidence": round1_confidence.get(result.agent_id),
            }
            for result in results
        ],
        "arbitration": arbitration,
        "appeal": serialize_appeal(case.appeal),
    }


def list_appealable_transactions(db: Session, user_id: str | None = None, limit: int = 50) -> list[dict]:
    stmt = select(Transaction).order_by(Transaction.created_at.desc()).limit(min(max(limit, 1), 100))
    if user_id:
        stmt = stmt.where(Transaction.user_id == user_id)
    transactions = db.execute(stmt).scalars().all()
    rows = []
    for transaction in transactions:
        decision = transaction.decision
        if not decision or decision.decision not in {"REVIEW", "BLOCK"}:
            continue
        alert = db.execute(select(Alert).where(Alert.transaction_id == transaction.transaction_id)).scalars().first()
        case = alert.review_case if alert else None
        rows.append(
            {
                "transaction_id": transaction.transaction_id,
                "case_id": case.case_id if case else "",
                "user_id": transaction.user_id,
                "amount": transaction.amount,
                "channel": transaction.channel,
                "counterparty_type": (transaction.raw_payload or {}).get("counterparty_type", transaction.merchant_id),
                "device_id": transaction.device_id,
                "location": transaction.location,
                "decision": decision.decision,
                "risk_score": decision.risk_score,
                "evidence_summary": decision.evidence_summary,
                "created_at": transaction.created_at.isoformat() if transaction.created_at else "",
                "case_status": case.status if case else "",
                "appeal": serialize_appeal(case.appeal if case else None),
            }
        )
    return rows


def submit_appeal(db: Session, payload: dict, trace_id: str, actor: str = "U2002") -> tuple[UserAppeal, str]:
    tx_id = payload["transaction_id"]
    transaction = db.execute(select(Transaction).where(Transaction.transaction_id == tx_id)).scalars().first()
    if not transaction or not transaction.decision or transaction.decision.decision not in {"REVIEW", "BLOCK"}:
        raise ValueError("只允许对异常交易发起申诉")
    alert = db.execute(select(Alert).where(Alert.transaction_id == tx_id)).scalars().first()
    if not alert or not alert.review_case:
        raise ValueError("交易尚未生成后台案件")

    case = alert.review_case
    materials = payload.get("materials") or []
    appeal = db.execute(select(UserAppeal).where(UserAppeal.case_id == case.case_id)).scalars().first()
    event = _timeline_event("用户提交申诉", "申诉原因和证明材料已进入案件证据链。")
    if appeal:
        appeal.reason = payload.get("reason", appeal.reason)
        appeal.materials = materials
        appeal.status = "SUBMITTED"
        appeal.timeline = [*(appeal.timeline or []), event]
    else:
        appeal = UserAppeal(
            appeal_id=f"AP-{uuid4().hex[:10]}",
            case_id=case.case_id,
            transaction_id=tx_id,
            user_id=payload.get("user_id") or transaction.user_id,
            status="SUBMITTED",
            reason=payload.get("reason", ""),
            materials=materials,
            timeline=[
                _timeline_event("系统识别异常交易", f"{transaction.decision.decision} 决策已生成案件 {case.case_id}。"),
                event,
            ],
            trace_id=trace_id,
        )
        db.add(appeal)

    case.status = "APPEALED"
    case.remark = f"用户申诉：{appeal.reason}"
    alert.status = "ASSIGNED"
    audit = write_audit(
        db,
        module="用户申诉",
        action="SubmitAppeal",
        target_type="UserAppeal",
        target_id=appeal.appeal_id,
        trace_id=trace_id,
        actor=actor,
        actor_role="CLIENT",
        detail={"transaction_id": tx_id, "case_id": case.case_id},
    )
    db.flush()
    return appeal, audit.log_id


def review_case(db: Session, payload: dict, trace_id: str, actor: str = "reviewer_01", actor_role: str = "ADMIN") -> tuple[ReviewCase, str]:
    case = db.execute(select(ReviewCase).where(ReviewCase.case_id == payload["case_id"])).scalars().first()
    if not case:
        raise ValueError("案件不存在")

    verdict = payload["review_result"]
    case.review_result = verdict
    case.reviewer = payload.get("reviewer", "reviewer_01")
    case.remark = payload.get("remark", "")

    supplement_values = {"需补充", "NEED_SUPPLEMENT"}
    fraud_values = {"欺诈", "FRAUD"}
    false_positive_values = {"误报", "FALSE_POSITIVE"}
    case.status = "NEED_SUPPLEMENT" if verdict in supplement_values else "COMPLETED"
    if case.alert:
        case.alert.status = "CLOSED" if case.status == "COMPLETED" else "ASSIGNED"

    if case.appeal:
        if verdict in supplement_values:
            case.appeal.status = "NEED_SUPPLEMENT"
            event = _timeline_event("需要补充材料", case.remark or "后台复核需要用户继续补充证明材料。")
        elif verdict in false_positive_values:
            case.appeal.status = "APPROVED"
            event = _timeline_event("申诉通过", case.remark or "后台确认该交易为误拦，处理结果已回写。")
        elif verdict in fraud_values:
            case.appeal.status = "REJECTED"
            event = _timeline_event("申诉驳回", case.remark or "后台确认风险成立，交易继续保持拦截。")
        else:
            case.appeal.status = "COMPLETED"
            event = _timeline_event("复核完成", case.remark or "后台复核已完成。")
        case.appeal.handler_note = case.remark
        case.appeal.timeline = [*(case.appeal.timeline or []), event]

    if case.status == "COMPLETED" and case.alert:
        label_map = {
            "欺诈": "FRAUD",
            "FRAUD": "FRAUD",
            "误报": "FALSE_POSITIVE",
            "FALSE_POSITIVE": "FALSE_POSITIVE",
            "待观察": "LEGIT",
            "LEGIT": "LEGIT",
        }
        label = label_map.get(verdict, "LEGIT")
        sample = FeedbackSample(
            sample_id=f"FS-{uuid4().hex[:10]}",
            transaction_id=case.alert.transaction_id,
            case_id=case.case_id,
            label=label,
            feature_snapshot={"remark": case.remark, "review_result": verdict},
            trace_id=trace_id,
        )
        db.add(sample)
        record_feedback(db, transaction_id=case.alert.transaction_id, label=label, trace_id=trace_id, actor=actor, actor_role=actor_role)

    audit = write_audit(
        db,
        module="案件复核",
        action="Review",
        target_type="ReviewCase",
        target_id=case.case_id,
        trace_id=trace_id,
        actor=actor,
        actor_role=actor_role,
        detail={"review_result": verdict, "remark": case.remark},
    )
    db.flush()
    if case.status == "COMPLETED" and case.alert:
        index_case(db, case.case_id)
    return case, audit.log_id
