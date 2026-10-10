from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StrategyConfig
from app.modules.audit.service import write_audit


DEFAULT_WEIGHTS = {
    "list-match": 0.24,
    "transaction-analysis": 0.19,
    "behavior-modeling": 0.15,
    "device-fingerprint": 0.10,
    "graph-trace": 0.17,
    "semantic-analysis": 0.15,
}


def get_active_strategy(db: Session) -> StrategyConfig:
    strategy = db.execute(
        select(StrategyConfig).where(StrategyConfig.status == "PUBLISHED").order_by(StrategyConfig.created_at.desc())
    ).scalars().first()
    if strategy:
        # 幂等演进：旧策略缺失新增 Agent 权重时，用默认值补齐并重新归一化到 1.0
        missing = {key: value for key, value in DEFAULT_WEIGHTS.items() if key not in strategy.agent_weights}
        if missing:
            merged = {**strategy.agent_weights, **missing}
            total = sum(float(value) for value in merged.values())
            strategy.agent_weights = {key: round(float(value) / total, 4) for key, value in merged.items()}
            db.flush()
        return strategy
    strategy = StrategyConfig(
        strategy_id="STR-default",
        name="默认协同检测策略",
        agent_weights=DEFAULT_WEIGHTS,
        conflict_threshold=0.4,
        review_threshold=0.6,
        block_threshold=0.85,
        rule_content={"trigger": "amount > 500000 or blacklist_hit == true"},
        version="V1.0",
        status="PUBLISHED",
        effective_time=datetime.utcnow(),
    )
    db.add(strategy)
    db.flush()
    return strategy


def validate_strategy_payload(payload: dict) -> tuple[bool, str]:
    weights = payload.get("agent_weights") or payload.get("agentWeights") or {}
    if weights:
        total = sum(float(value) for value in weights.values())
        if abs(total - 1.0) > 0.01:
            return False, "Agent 权重合计必须为 1.0"
    threshold = float(payload.get("conflict_threshold", payload.get("conflictThreshold", 0.4)))
    if threshold <= 0 or threshold >= 1:
        return False, "冲突阈值必须在 0 到 1 之间"
    return True, "策略校验通过"


def publish_strategy(db: Session, payload: dict, trace_id: str, actor: str = "admin_01", actor_role: str = "ADMIN") -> tuple[StrategyConfig, str]:
    ok, message = validate_strategy_payload(payload)
    if not ok:
        raise ValueError(message)
    current = get_active_strategy(db)
    current.status = "INACTIVE"
    next_strategy = StrategyConfig(
        strategy_id=f"STR-{uuid4().hex[:10]}",
        name=payload.get("name", "策略配置发布"),
        agent_weights=payload.get("agent_weights") or payload.get("agentWeights") or current.agent_weights,
        conflict_threshold=float(payload.get("conflict_threshold", payload.get("conflictThreshold", current.conflict_threshold))),
        review_threshold=float(payload.get("review_threshold", payload.get("reviewThreshold", current.review_threshold))),
        block_threshold=float(payload.get("block_threshold", payload.get("blockThreshold", current.block_threshold))),
        rule_content=payload.get("rule_content") or payload.get("ruleContent") or current.rule_content,
        version=payload.get("version", f"V{int(current.version.replace('V', '').split('.')[0] or 1)}.1"),
        status="PUBLISHED",
        effective_time=datetime.utcnow(),
    )
    db.add(next_strategy)
    audit = write_audit(
        db,
        module="策略配置",
        action="Publish",
        target_type="StrategyConfig",
        target_id=next_strategy.strategy_id,
        trace_id=trace_id,
        actor=actor,
        actor_role=actor_role,
        detail={"version": next_strategy.version},
    )
    db.flush()
    return next_strategy, audit.log_id


def serialize_strategy(strategy: StrategyConfig) -> dict:
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "agent_weights": strategy.agent_weights,
        "conflict_threshold": strategy.conflict_threshold,
        "review_threshold": strategy.review_threshold,
        "block_threshold": strategy.block_threshold,
        "rule_content": strategy.rule_content,
        "version": strategy.version,
        "status": strategy.status,
        "effective_time": strategy.effective_time.isoformat() if strategy.effective_time else None,
    }
