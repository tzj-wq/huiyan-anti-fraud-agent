import pytest
from fastapi import HTTPException

from app.core.response import api_response, ensure_trace_id
from app.core.security import require_confirm_token
from app.modules.strategy.service import DEFAULT_WEIGHTS, validate_strategy_payload


def test_strategy_validation_accepts_balanced_weights():
    ok, message = validate_strategy_payload(
        {
            "agent_weights": DEFAULT_WEIGHTS,
            "conflict_threshold": 0.4,
        }
    )

    assert ok is True
    assert message


def test_strategy_validation_rejects_unbalanced_weights():
    ok, message = validate_strategy_payload(
        {
            "agent_weights": {
                "list-match": 0.5,
                "transaction-analysis": 0.5,
                "behavior-modeling": 0.5,
            }
        }
    )

    assert ok is False
    assert "1.0" in message


def test_strategy_validation_rejects_invalid_conflict_threshold():
    ok, message = validate_strategy_payload({"conflict_threshold": 1.2})

    assert ok is False
    assert message


def test_confirm_token_is_required_for_high_risk_actions():
    require_confirm_token("demo-confirm")

    with pytest.raises(HTTPException) as exc:
        require_confirm_token("wrong-token")

    assert exc.value.status_code == 400


def test_api_response_has_trace_timestamp_and_optional_audit_id():
    trace_id = ensure_trace_id()
    response = api_response({"ok": True}, trace_id=trace_id, audit_id="AUD-UNIT")

    assert response["code"] == 0
    assert response["data"] == {"ok": True}
    assert response["trace_id"] == trace_id
    assert response["audit_id"] == "AUD-UNIT"
    assert response["timestamp"]
