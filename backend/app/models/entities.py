from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class UserProfile(Base, TimestampMixin):
    __tablename__ = "t_user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_name: Mapped[str] = mapped_column(String(128), default="")
    phone_hash: Mapped[str] = mapped_column(String(128), default="")
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    last_login_location: Mapped[str] = mapped_column(String(64), default="")
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Transaction(Base, TimestampMixin):
    __tablename__ = "t_transaction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(12), default="CNY")
    channel: Mapped[str] = mapped_column(String(32), default="APP")
    device_id: Mapped[str] = mapped_column(String(64), default="")
    merchant_id: Mapped[str] = mapped_column(String(64), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(64), default="")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    agent_results: Mapped[list["AgentResult"]] = relationship(back_populates="transaction")
    decision: Mapped[Optional["DecisionRecord"]] = relationship(back_populates="transaction")


class AgentResult(Base, TimestampMixin):
    __tablename__ = "t_agent_result"
    __table_args__ = (UniqueConstraint("transaction_id", "agent_id", name="uq_agent_transaction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("t_transaction.transaction_id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_type: Mapped[str] = mapped_column(String(64))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_label: Mapped[str] = mapped_column(String(64), default="")
    evidence_list: Mapped[list] = mapped_column(JSON, default=list)
    exec_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)

    transaction: Mapped[Transaction] = relationship(back_populates="agent_results")


class DecisionRecord(Base, TimestampMixin):
    __tablename__ = "t_decision_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("t_transaction.transaction_id"), unique=True, index=True)
    decision: Mapped[str] = mapped_column(String(16), index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    risk_labels: Mapped[list] = mapped_column(JSON, default=list)
    evidence_summary: Mapped[str] = mapped_column(Text, default="")
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)

    transaction: Mapped[Transaction] = relationship(back_populates="decision")
    alert: Mapped[Optional["Alert"]] = relationship(back_populates="decision")


class Alert(Base, TimestampMixin):
    __tablename__ = "t_alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("t_transaction.transaction_id"), index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("t_decision_record.decision_id"), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    assignee: Mapped[str] = mapped_column(String(64), default="reviewer_01", index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    decision: Mapped[DecisionRecord] = relationship(back_populates="alert")
    review_case: Mapped[Optional["ReviewCase"]] = relationship(back_populates="alert")


class ReviewCase(Base, TimestampMixin):
    __tablename__ = "t_review_case"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("t_alert.alert_id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="P1", index=True)
    review_result: Mapped[str] = mapped_column(String(32), default="")
    reviewer: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)

    alert: Mapped[Alert] = relationship(back_populates="review_case")
    appeal: Mapped[Optional["UserAppeal"]] = relationship(back_populates="review_case")


class UserAppeal(Base, TimestampMixin):
    __tablename__ = "t_user_appeal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appeal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("t_review_case.case_id"), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="SUBMITTED", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    materials: Mapped[list] = mapped_column(JSON, default=list)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    handler_note: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str] = mapped_column(String(64), index=True)

    review_case: Mapped[ReviewCase] = relationship(back_populates="appeal")


class FeedbackSample(Base, TimestampMixin):
    __tablename__ = "t_feedback_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(32), index=True)
    feature_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)


class AuditLog(Base):
    __tablename__ = "t_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    actor_role: Mapped[str] = mapped_column(String(32), default="ADMIN")
    action: Mapped[str] = mapped_column(String(64), index=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(24), default="SUCCESS")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)


class StrategyConfig(Base, TimestampMixin):
    __tablename__ = "t_strategy_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    conflict_threshold: Mapped[float] = mapped_column(Float, default=0.4)
    review_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    block_threshold: Mapped[float] = mapped_column(Float, default=0.85)
    rule_content: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[str] = mapped_column(String(24), default="V1.0")
    status: Mapped[str] = mapped_column(String(24), default="PUBLISHED", index=True)
    effective_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rollback_reason: Mapped[str] = mapped_column(Text, default="")


class DecisionProcess(Base, TimestampMixin):
    __tablename__ = "t_decision_process"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("t_transaction.transaction_id"), unique=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    stages: Mapped[dict] = mapped_column(JSON, default=dict)
    arbitration_used: Mapped[bool] = mapped_column(Boolean, default=False)
    arbitration_method: Mapped[str] = mapped_column(String(16), default="none")
    total_rounds: Mapped[int] = mapped_column(Integer, default=1)
    stage1_ms: Mapped[int] = mapped_column(Integer, default=0)
    stage2_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)


class AgentPerformance(Base, TimestampMixin):
    __tablename__ = "t_agent_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    total_samples: Mapped[int] = mapped_column(Integer, default=0)
    correct_ewma: Mapped[float] = mapped_column(Float, default=0.7)
    recent_history: Mapped[list] = mapped_column(JSON, default=list)
    learned_weight: Mapped[float] = mapped_column(Float, default=0.0)


class RiskListItem(Base, TimestampMixin):
    __tablename__ = "t_risk_list"
    __table_args__ = (UniqueConstraint("list_type", "item_value", name="uq_risk_list_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    list_type: Mapped[str] = mapped_column(String(24), index=True)
    item_value: Mapped[str] = mapped_column(String(128), index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="HIGH")
    status: Mapped[str] = mapped_column(String(24), default="APPROVED", index=True)
    source: Mapped[str] = mapped_column(String(64), default="seed")
    owner: Mapped[str] = mapped_column(String(64), default="admin_01")
    reviewer: Mapped[str] = mapped_column(String(64), default="reviewer_01")
    description: Mapped[str] = mapped_column(Text, default="")
