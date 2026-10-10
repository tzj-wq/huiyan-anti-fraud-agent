from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_trace_id(request: Request | None = None) -> str:
    if request is None:
        return f"TR-{uuid4().hex[:16]}"
    return request.headers.get("X-Trace-ID") or f"TR-{uuid4().hex[:16]}"


def api_response(
    data: Any = None,
    message: str = "success",
    trace_id: str | None = None,
    code: int = 0,
    audit_id: str | None = None,
) -> dict[str, Any]:
    body = {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": trace_id or f"TR-{uuid4().hex[:16]}",
        "timestamp": now_iso(),
    }
    body["code"] = code
    if audit_id:
        body["audit_id"] = audit_id
    return body
