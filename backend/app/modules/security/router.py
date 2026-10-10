from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.llm import LLMClient
from app.core.response import api_response, ensure_trace_id
from app.core.security import require_roles

router = APIRouter(prefix="/security", tags=["security"])


class SecurityCheckRequest(BaseModel):
    devices: list[dict] = Field(default_factory=list)
    mfa: dict = Field(default_factory=dict)
    privacy_items: list[dict] = Field(default_factory=list)
    recent_logs: list[dict] = Field(default_factory=list)


@router.post("/check")
def check_security(request: Request, payload: SecurityCheckRequest, principal=Depends(require_roles("CLIENT", "ADMIN"))):
    trace = ensure_trace_id(request)
    result = LLMClient().assess_security(payload.model_dump())
    return api_response(result, trace_id=trace)
