"""反馈驱动的 Agent 权重学习：复核结论 → 逐 Agent 正确性信号 → EWMA + 贝叶斯收缩 → softmax 学习权重。

设计要点：
- 每次案件复核完成（FRAUD/FALSE_POSITIVE/LEGIT），把该交易各 Agent 的评分与人工标签比对，
  生成 0/1 正确性信号并按 EWMA(α=0.3) 更新各 Agent 的滚动准确率；
- 收缩（向先验 0.7 收缩，强度 K=10）保证小样本时学习权重不偏离配置权重过远；
- softmax(T=0.2) 把收缩准确率映射为和为 1 的学习权重；
- 采纳需管理员显式确认（人工在环），走与手工发布一致的校验/审计/版本化流程。
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentPerformance, AgentResult
from app.modules.audit.service import write_audit
from app.modules.strategy.service import get_active_strategy, publish_strategy

EWMA_ALPHA = 0.3
PRIOR_ACCURACY = 0.7
SHRINKAGE_K = 10.0
SOFTMAX_TEMPERATURE = 0.3
HISTORY_LIMIT = 20
MIN_READY_SAMPLES = 5
MIN_ACTIVE_AGENTS = 3


def correctness_signal(agent_score: float, label: str, review_threshold: float) -> int:
    if label == "FRAUD":
        return 1 if agent_score >= review_threshold else 0
    return 1 if agent_score < review_threshold else 0


def shrunk_accuracy(perf: AgentPerformance) -> float:
    n = perf.total_samples
    return (n * perf.correct_ewma + SHRINKAGE_K * PRIOR_ACCURACY) / (n + SHRINKAGE_K)


def compute_learned_weights(db: Session) -> dict[str, float]:
    rows = db.execute(select(AgentPerformance)).scalars().all()
    if not rows:
        return {}
    exps = {row.agent_id: math.exp(shrunk_accuracy(row) / SOFTMAX_TEMPERATURE) for row in rows}
    total = sum(exps.values())
    return {agent_id: round(value / total, 4) for agent_id, value in exps.items()}


def _persist_learned_weights(db: Session) -> None:
    weights = compute_learned_weights(db)
    rows = db.execute(select(AgentPerformance)).scalars().all()
    for row in rows:
        row.learned_weight = weights.get(row.agent_id, 0.0)


def record_feedback(db: Session, transaction_id: str, label: str, trace_id: str, actor: str = "reviewer_01", actor_role: str = "ADMIN") -> None:
    strategy = get_active_strategy(db)
    results = db.execute(select(AgentResult).where(AgentResult.transaction_id == transaction_id)).scalars().all()
    if not results:
        return
    existing = {row.agent_id: row for row in db.execute(select(AgentPerformance)).scalars().all()}
    for result in results:
        if result.degraded:
            continue  # 降级 Agent 未产生真实判断（LLM 不可用/超时），不计入学习信号
        correct = correctness_signal(result.risk_score, label, strategy.review_threshold)
        perf = existing.get(result.agent_id)
        if perf is None:
            perf = AgentPerformance(agent_id=result.agent_id, total_samples=0, correct_ewma=PRIOR_ACCURACY, recent_history=[], learned_weight=0.0)
            db.add(perf)
            existing[result.agent_id] = perf
        perf.correct_ewma = round(EWMA_ALPHA * correct + (1 - EWMA_ALPHA) * perf.correct_ewma, 4)
        perf.total_samples += 1
        perf.recent_history = [
            *(perf.recent_history or [])[-(HISTORY_LIMIT - 1):],
            {
                "transaction_id": transaction_id,
                "agent_score": result.risk_score,
                "label": label,
                "correct": correct,
                "ewma_after": perf.correct_ewma,
                "ts": datetime.utcnow().isoformat(),
            },
        ]
    db.flush()
    _persist_learned_weights(db)
    write_audit(
        db,
        module="权重学习",
        action="RecordFeedback",
        target_type="Transaction",
        target_id=transaction_id,
        trace_id=trace_id,
        actor=actor,
        actor_role=actor_role,
        detail={"label": label, "agents": len(results)},
    )


def get_learning_stats(db: Session) -> dict:
    strategy = get_active_strategy(db)
    rows = db.execute(select(AgentPerformance)).scalars().all()
    by_agent = {row.agent_id: row for row in rows}
    agents = []
    for agent_id, configured_weight in strategy.agent_weights.items():
        row = by_agent.get(agent_id)
        agents.append(
            {
                "agent_id": agent_id,
                "configured_weight": configured_weight,
                "learned_weight": row.learned_weight if row and row.learned_weight else configured_weight,
                "total_samples": row.total_samples if row else 0,
                "correct_ewma": row.correct_ewma if row else None,
                "shrunk_accuracy": round(shrunk_accuracy(row), 4) if row else None,
                "recent_history": (row.recent_history or []) if row else [],
            }
        )
    # 有效参与学习的 Agent（有样本）才参与 ready 判定；降级剔除的 Agent（如 LLM 关闭时的语义 Agent）不阻塞采纳
    active = [agent for agent in agents if agent["total_samples"] > 0]
    ready = (
        len(active) >= MIN_ACTIVE_AGENTS
        and all(agent["total_samples"] >= MIN_READY_SAMPLES for agent in active)
    )
    return {
        "agents": agents,
        "ready": ready,
        "min_ready_samples": MIN_READY_SAMPLES,
        "review_threshold": strategy.review_threshold,
        "ewma_alpha": EWMA_ALPHA,
        "prior_accuracy": PRIOR_ACCURACY,
    }


def adopt_learned_weights(db: Session, trace_id: str, actor: str = "admin_01", actor_role: str = "ADMIN") -> tuple:
    strategy = get_active_strategy(db)
    stats = get_learning_stats(db)
    merged = {
        agent["agent_id"]: (agent["learned_weight"] if agent["total_samples"] > 0 else agent["configured_weight"])
        for agent in stats["agents"]
    }
    total = sum(merged.values())
    if not merged or total <= 0:
        raise ValueError("暂无可采纳的学习权重")
    normalized = {agent_id: round(weight / total, 4) for agent_id, weight in merged.items()}
    drift = round(1.0 - sum(normalized.values()), 4)
    if drift:
        top = max(normalized, key=normalized.get)
        normalized[top] = round(normalized[top] + drift, 4)
    payload = {
        "name": "学习权重采纳",
        "agent_weights": normalized,
        "conflict_threshold": strategy.conflict_threshold,
        "review_threshold": strategy.review_threshold,
        "block_threshold": strategy.block_threshold,
        "version": f"V{int(strategy.version.replace('V', '').split('.')[0] or 1) + 1}.0",
    }
    return publish_strategy(db, payload, trace_id, actor, actor_role)
