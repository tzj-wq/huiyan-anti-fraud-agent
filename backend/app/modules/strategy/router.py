from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.llm import LLMClient
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_confirm_token, require_roles
from app.modules.strategy.learning import adopt_learned_weights, get_learning_stats
from app.modules.strategy.service import get_active_strategy, publish_strategy, serialize_strategy, validate_strategy_payload

router = APIRouter(prefix="/strategies", tags=["strategy"])


class StrategyPublishRequest(BaseModel):
    name: str = "策略配置发布"
    agent_weights: dict[str, float] = Field(default_factory=dict)
    conflict_threshold: float = 0.4
    review_threshold: float = 0.6
    block_threshold: float = 0.85
    rule_content: dict = Field(default_factory=dict)
    confirm_token: str | None = None


@router.get("/active")
def active_strategy(request: Request, db: Session = Depends(get_db), principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR"))):
    trace = ensure_trace_id(request)
    return api_response(serialize_strategy(get_active_strategy(db)), trace_id=trace)


@router.get("/llm/status")
def llm_status(request: Request, principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR"))):
    trace = ensure_trace_id(request)
    return api_response(LLMClient().status(), trace_id=trace)


@router.post("/validate")
def validate_strategy(request: Request, payload: StrategyPublishRequest, principal=Depends(require_roles("ADMIN"))):
    trace = ensure_trace_id(request)
    ok, message = validate_strategy_payload(payload.model_dump())
    return api_response({"valid": ok, "message": message}, message=message, trace_id=trace)


@router.post("/publish")
def publish(
    request: Request,
    payload: StrategyPublishRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN")),
):
    trace = ensure_trace_id(request)
    require_confirm_token(payload.confirm_token)
    try:
        strategy, audit_id = publish_strategy(db, payload.model_dump(), trace, actor=principal.user_id, actor_role=principal.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return api_response(serialize_strategy(strategy), message="策略发布成功", trace_id=trace, audit_id=audit_id)


@router.get("/learning")
def learning(request: Request, db: Session = Depends(get_db), principal=Depends(require_roles("ADMIN", "OPERATOR", "AUDITOR"))):
    trace = ensure_trace_id(request)
    return api_response(get_learning_stats(db), trace_id=trace)


class AdoptLearnedRequest(BaseModel):
    confirm_token: str | None = None


@router.post("/adopt-learned")
def adopt_learned(
    request: Request,
    payload: AdoptLearnedRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_roles("ADMIN")),
):
    trace = ensure_trace_id(request)
    require_confirm_token(payload.confirm_token)
    try:
        strategy, audit_id = adopt_learned_weights(db, trace, actor=principal.user_id, actor_role=principal.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return api_response(serialize_strategy(strategy), message="学习权重已采纳并发布新版本", trace_id=trace, audit_id=audit_id)
