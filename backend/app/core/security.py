from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str


DEMO_TOKENS: dict[str, Principal] = {
    "demo-admin-token": Principal(user_id="admin_01", role="ADMIN"),
    "demo-operator-token": Principal(user_id="operator_01", role="OPERATOR"),
    "demo-auditor-token": Principal(user_id="auditor_01", role="AUDITOR"),
    "demo-client-token": Principal(user_id="U2002", role="CLIENT"),
}

CONFIRM_TOKEN = "demo-confirm"
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    principal = DEMO_TOKENS.get(credentials.credentials)
    if not principal:
        raise HTTPException(status_code=401, detail="无效的 Bearer Token")
    return principal


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
        if allowed and principal.role not in allowed:
            raise HTTPException(status_code=403, detail="当前角色无权访问该接口")
        return principal

    return dependency


def require_confirm_token(confirm_token: str | None) -> None:
    if confirm_token != CONFIRM_TOKEN:
        raise HTTPException(status_code=400, detail="高风险操作需要有效的二次确认令牌")
