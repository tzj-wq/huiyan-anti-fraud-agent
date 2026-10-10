from __future__ import annotations
from time import perf_counter
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentResult, Alert, DecisionProcess, DecisionRecord, ReviewCase, Transaction, UserProfile
from app.core.llm import LLMClient
from app.modules.audit.service import write_audit
from app.modules.detection.agents import AGENTS, AgentOutput
from app.modules.detection.collaboration import (
    ArbitrationVerdict,
    analyze_conflict,
    arbitrate,
    build_fusion_stage,
    build_stage1,
    build_stage2,
    decide,
    fuse,
)
from app.modules.detection.graph_workflow import _run_agents_parallel, detect_via_langgraph
from app.modules.risklist.service import check_risk_list
from app.modules.strategy.service import get_active_strategy


def _transaction_id() -> str:
    return f"TX-{uuid4().hex[:12]}"


def _store_agent_result(db: Session, transaction_id: str, output: AgentOutput) -> None:
    db.add(
        AgentResult(
            result_id=f"AR-{uuid4().hex[:12]}",
            transaction_id=transaction_id,
            agent_id=output.agent_id,
            agent_type=output.agent_type,
            risk_score=output.risk_score,
            risk_label=output.risk_label,
            evidence_list=output.evidence,
            exec_time_ms=output.exec_time_ms,
            degraded=output.degraded,
        )
    )


def _feature_bundle(db: Session, payload: dict) -> dict:
    user = db.execute(select(UserProfile).where(UserProfile.user_id == payload.get("user_id"))).scalars().first()
    list_values = [payload.get("user_id"), payload.get("device_id"), payload.get("ip_address"), payload.get("merchant_id")]
    blacklist_hit = any(check_risk_list(db, list_type=None, value=value) for value in list_values if value)
    list_fields_checked = sum(1 for value in list_values if value)
    target_type = payload.get("counterparty_type", "")
    device_id = str(payload.get("device_id", ""))
    risk_hops = 1
    if payload.get("merchant_id") == "MCH-RISK-001" or target_type == "对私转账（陌生人）":
        risk_hops = 4
    elif target_type == "个人卖家":
        risk_hops = 2
    elif target_type == "对私转账（熟人）":
        risk_hops = 0
    shared_device_count = 1
    if device_id.endswith("X"):
        shared_device_count = 4
    elif "WINDOWS" in device_id.upper():
        shared_device_count = 2
    # 非结构化语义线索：显式 context_clues，或申诉理由/备注/材料等字段
    semantic_clues: list[str] = []
    raw_clues = payload.get("context_clues")
    if isinstance(raw_clues, list):
        semantic_clues = [str(item).strip() for item in raw_clues if str(item).strip()]
    for key in ("appeal_reason", "remark", "note"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            semantic_clues.append(value.strip())
    return {
        "blacklist_hit": blacklist_hit,
        "list_fields_checked": list_fields_checked,
        "has_profile": bool(user),
        "last_login_location": user.last_login_location if user else payload.get("home_location", ""),
        "shared_device_count": shared_device_count,
        "risk_graph_hops": risk_hops,
        "semantic_clues": semantic_clues,
    }


def _collaborative_decide(payload: dict, features: dict, strategy) -> tuple[str, float, bool, list[AgentOutput], dict, dict]:
    """两阶段协同决策：独立评估 → 冲突分析 → 条件仲裁 → 置信度加权融合。"""
    stage1_start = perf_counter()
    outputs = _run_agents_parallel(payload, features)
    stage1_ms = max(1, int((perf_counter() - stage1_start) * 1000))

    stage2_start = perf_counter()
    report = analyze_conflict(outputs, strategy)
    if report.needs_arbitration:
        verdict = arbitrate(payload, outputs, report, strategy, llm_client=LLMClient())
    else:
        verdict = ArbitrationVerdict.not_triggered()
    stage2_ms = max(0, int((perf_counter() - stage2_start) * 1000))

    fusion = fuse(outputs, strategy.agent_weights, verdict)
    decision = decide(outputs, fusion, verdict, strategy)

    rounds = [build_stage1(outputs)]
    if verdict.triggered:
        rounds.append(build_stage2(report, verdict))
    trace = {
        "rounds": rounds,
        "fusion": build_fusion_stage(fusion, verdict),
        "conflict": {
            "has_conflict": report.has_conflict,
            "spread": report.spread,
            "median_score": report.median_score,
            "trigger_reason": report.trigger_reason,
        },
    }
    timings = {"stage1_ms": stage1_ms, "stage2_ms": stage2_ms, "total_ms": stage1_ms + stage2_ms}
    return decision, fusion.risk_score, report.has_conflict, outputs, trace, timings


def detect_transaction(db: Session, payload: dict, trace_id: str) -> dict:
    tx_id = payload.get("transaction_id") or _transaction_id()
    payload = payload | {"transaction_id": tx_id}
    transaction = Transaction(
        transaction_id=tx_id,
        user_id=payload.get("user_id", "U-demo"),
        amount=float(payload.get("amount") or 0),
        currency=payload.get("currency", "CNY"),
        channel=payload.get("channel", "APP"),
        device_id=payload.get("device_id", ""),
        merchant_id=payload.get("merchant_id", ""),
        ip_address=payload.get("ip_address", ""),
        location=payload.get("location", ""),
        trace_id=trace_id,
        raw_payload=payload,
    )
    db.add(transaction)
    db.flush()

    strategy = get_active_strategy(db)
    features = _feature_bundle(db, payload)
    try:
        decision, risk_score, conflict_flag, outputs, trace, timings = detect_via_langgraph(payload, features, strategy)
    except Exception:
        decision, risk_score, conflict_flag, outputs, trace, timings = _collaborative_decide(payload, features, strategy)
    for output in outputs:
        _store_agent_result(db, tx_id, output)

    labels = sorted({output.risk_label for output in outputs if output.risk_label})
    agent_payloads = [
        {
            "agent_id": output.agent_id,
            "risk_score": output.risk_score,
            "risk_label": output.risk_label,
            "confidence": output.confidence,
            "degraded": output.degraded,
            "evidence": output.evidence,
        }
        for output in outputs
    ]
    llm_insight = LLMClient().explain_decision(
        transaction=payload,
        agent_outputs=agent_payloads,
        decision=decision,
        risk_score=risk_score,
    )
    summary = llm_insight.summary
    transaction.status = decision
    decision_id = f"DR-{uuid4().hex[:12]}"
    record = DecisionRecord(
        decision_id=decision_id,
        transaction_id=tx_id,
        decision=decision,
        risk_score=risk_score,
        risk_labels=labels,
        evidence_summary=summary,
        conflict_flag=conflict_flag,
        agent_count=len(outputs),
        trace_id=trace_id,
    )
    db.add(record)
    db.add(
        DecisionProcess(
            process_id=f"DP-{uuid4().hex[:12]}",
            transaction_id=tx_id,
            trace_id=trace_id,
            stages=trace,
            arbitration_used=trace["rounds"] and len(trace["rounds"]) > 1,
            arbitration_method=trace["rounds"][1]["method"] if len(trace["rounds"]) > 1 else "none",
            total_rounds=len(trace["rounds"]),
            stage1_ms=timings["stage1_ms"],
            stage2_ms=timings["stage2_ms"],
            total_ms=timings["total_ms"],
        )
    )
    write_audit(
        db,
        module="实时交易检测",
        action="Detect",
        target_type="Transaction",
        target_id=tx_id,
        trace_id=trace_id,
        detail={"decision": decision, "risk_score": risk_score},
    )

    alert_payload = None
    if decision in {"REVIEW", "BLOCK"}:
        level = "critical" if decision == "BLOCK" or risk_score >= 0.85 else "high"
        alert = Alert(
            alert_id=f"AL-{uuid4().hex[:12]}",
            transaction_id=tx_id,
            decision_id=decision_id,
            level=level,
            status="OPEN",
            title=f"{decision} 风险交易告警",
            detail=summary,
            trace_id=trace_id,
        )
        db.add(alert)
        db.flush()
        case = ReviewCase(
            case_id=f"CASE-{uuid4().hex[:10]}",
            alert_id=alert.alert_id,
            status="PENDING",
            priority="P0" if level == "critical" else "P1",
            trace_id=trace_id,
        )
        db.add(case)
        alert_payload = {"alert_id": alert.alert_id, "case_id": case.case_id, "level": level}
        write_audit(
            db,
            module="告警管理",
            action="CreateAlert",
            target_type="Alert",
            target_id=alert.alert_id,
            trace_id=trace_id,
            detail=alert_payload,
        )

    db.commit()
    return {
        "transaction_id": tx_id,
        "decision": decision,
        "risk_score": risk_score,
        "evidence_summary": summary,
        "recommendation": llm_insight.recommendation,
        "llm": {
            "enabled": llm_insight.enabled,
            "provider": llm_insight.provider,
            "model": llm_insight.model,
            "fallback": llm_insight.fallback,
        },
        "agent_results": agent_payloads,
        "conflict_flag": int(conflict_flag),
        "agent_count": len(outputs),
        "risk_labels": labels,
        "alert": alert_payload,
        "collaboration": trace | {"stage_ms": timings},
    }


def get_decision_process(db: Session, transaction_id: str) -> dict | None:
    process = db.execute(
        select(DecisionProcess).where(DecisionProcess.transaction_id == transaction_id)
    ).scalars().first()
    if not process:
        return None
    return {
        "process_id": process.process_id,
        "transaction_id": process.transaction_id,
        "trace_id": process.trace_id,
        "stages": process.stages,
        "arbitration_used": process.arbitration_used,
        "arbitration_method": process.arbitration_method,
        "total_rounds": process.total_rounds,
        "stage1_ms": process.stage1_ms,
        "stage2_ms": process.stage2_ms,
        "total_ms": process.total_ms,
        "created_at": process.created_at.isoformat() if process.created_at else "",
    }


def list_transactions(db: Session, keyword: str | None = None, limit: int = 50, user_id: str | None = None) -> list[dict]:
    limit = min(max(limit, 1), 100)
    stmt = select(Transaction).order_by(Transaction.created_at.desc())
    if user_id:
        stmt = stmt.where(Transaction.user_id == user_id)
    if keyword:
        stmt = stmt.limit(limit * 5)
    else:
        stmt = stmt.limit(limit)
    transactions = db.execute(stmt).scalars().all()
    rows = []
    for transaction in transactions:
        decision = transaction.decision
        row = {
            "transaction_id": transaction.transaction_id,
            "user_id": transaction.user_id,
            "amount": transaction.amount,
            "channel": transaction.channel,
            "device_id": transaction.device_id,
            "merchant_id": transaction.merchant_id,
            "location": transaction.location,
            "status": transaction.status,
            "trace_id": transaction.trace_id,
            "created_at": transaction.created_at.isoformat() if transaction.created_at else "",
            "decision": decision.decision if decision else transaction.status,
            "risk_score": decision.risk_score if decision else 0,
            "risk_labels": decision.risk_labels if decision else [],
            "evidence_summary": decision.evidence_summary if decision else "",
            "raw_payload": transaction.raw_payload,
        }
        if keyword:
            haystack = " ".join(str(value) for value in row.values()).lower()
            if keyword.lower() not in haystack:
                continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows
