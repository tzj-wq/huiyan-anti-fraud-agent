from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.core.llm import LLMClient, LLMDecisionInsight
from app.main import app
from app.seed import seed_demo_data

# 测试确定性：全局关闭真实 LLM 调用（explain_decision 走 fallback、语义 Agent 降级），
# 避免依赖外部 API 与消耗配额；LLM 参与融合的路径由独立用例局部 mock 验证。
_patch_enabled = patch.object(LLMClient, "enabled", return_value=False)
_patch_enabled.start()

init_db()
db = SessionLocal()
try:
    seed_demo_data(db)
finally:
    db.close()

client = TestClient(app)
client.headers.update({"Authorization": "Bearer demo-admin-token"})


def test_protected_endpoint_requires_token():
    response = TestClient(app).get("/api/v1/audit/logs")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 401
    assert body["trace_id"].startswith("TR-")


def test_client_role_can_only_use_client_scope():
    scoped_client = TestClient(app)
    scoped_client.headers.update({"Authorization": "Bearer demo-client-token"})
    response = scoped_client.get("/api/v1/detect/transactions?limit=10")
    assert response.status_code == 200
    assert all(row["user_id"] == "U2002" for row in response.json()["data"])

    denied = scoped_client.get("/api/v1/audit/logs")
    assert denied.status_code == 403


def test_low_risk_transaction_passes():
    response = client.post(
        "/api/v1/detect/transaction",
        json={
            "transaction": {
                "user_id": "U1001",
                "amount": 1200,
                "channel": "APP",
                "device_id": "DEV-1001",
                "merchant_id": "MCH-NORMAL-001",
                "location": "上海",
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["decision"] == "PASS"
    assert data["agent_count"] == 6


def test_semantic_agent_degrades_when_no_clues():
    """无 context_clues 且 LLM 关闭时，语义 Agent 降级剔除，不改变决策。"""
    response = client.post(
        "/api/v1/detect/transaction",
        json={
            "transaction": {
                "user_id": "U1001",
                "amount": 1200,
                "channel": "APP",
                "device_id": "DEV-1001",
                "merchant_id": "MCH-NORMAL-001",
                "location": "上海",
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["agent_count"] == 6
    semantic = next(item for item in data["agent_results"] if item["agent_id"] == "semantic-analysis")
    assert semantic["degraded"] is True
    assert semantic["risk_label"] == "LLM_UNAVAILABLE"
    assert data["decision"] == "PASS"


def test_semantic_agent_joins_fusion_when_llm_available():
    """LLM 可用且有语义线索时，语义 Agent 输出真实风险信号并参与融合。"""
    fake_semantic = {
        "risk_score": 0.22,
        "risk_label": "SEMANTIC_LOW_RISK",
        "evidence": [{"summary": "提供交易凭证，背景自洽", "score": 0.22}],
        "confidence": 0.85,
    }
    fake_insight = LLMDecisionInsight(
        enabled=True,
        provider="deepseek",
        model="test",
        summary="测试摘要",
        recommendation="测试建议",
        evidence=["测试证据"],
        audit_note="测试审计说明",
    )
    with patch.object(LLMClient, "enabled", return_value=True), \
         patch.object(LLMClient, "analyze_semantic_risk", return_value=fake_semantic), \
         patch.object(LLMClient, "explain_decision", return_value=fake_insight):
        response = client.post(
            "/api/v1/detect/transaction",
            json={
                "transaction": {
                    "user_id": "U1001",
                    "amount": 1200,
                    "channel": "APP",
                    "device_id": "DEV-1001",
                    "merchant_id": "MCH-NORMAL-001",
                    "location": "上海",
                    "context_clues": ["用户申诉称是本人真实交易，已提供交易凭证"],
                }
            },
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["agent_count"] == 6
    semantic = next(item for item in data["agent_results"] if item["agent_id"] == "semantic-analysis")
    assert semantic["degraded"] is False
    assert semantic["risk_label"] == "SEMANTIC_LOW_RISK"
    assert semantic["risk_score"] == pytest.approx(0.22, abs=0.05)


def test_blacklist_hit_blocks_and_creates_case():
    response = client.post(
        "/api/v1/detect/transaction",
        json={
            "transaction": {
                "user_id": "U9009",
                "amount": 1240000,
                "channel": "WEB",
                "device_id": "DEV-RISK-X",
                "merchant_id": "MCH-RISK-001",
                "location": "上海",
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["decision"] == "BLOCK"
    assert data["alert"]["case_id"].startswith("CASE-")


def test_agent_conflict_enters_review():
    response = client.post(
        "/api/v1/detect/transaction",
        json={
            "transaction": {
                "user_id": "U1001",
                "amount": 900000,
                "channel": "APP",
                "device_id": "DEV-1001",
                "merchant_id": "MCH-NORMAL-001",
                "location": "上海",
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conflict_flag"] == 1
    assert data["decision"] in {"REVIEW", "BLOCK"}


def test_case_review_generates_feedback_and_audit():
    cases = client.get("/api/v1/cases").json()["data"]
    target = next(item for item in cases if item["status"] != "COMPLETED")
    response = client.post(
        "/api/v1/cases/review",
        json={
            "case_id": target["case_id"],
            "review_result": "欺诈",
            "remark": "测试复核闭环",
            "confirm_token": "demo-confirm",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "COMPLETED"
    assert response.json()["audit_id"].startswith("AUD-")


def test_case_review_requires_confirm_token():
    cases = client.get("/api/v1/cases").json()["data"]
    target = next(item for item in cases if item["status"] != "COMPLETED")
    response = client.post(
        "/api/v1/cases/review",
        json={
            "case_id": target["case_id"],
            "review_result": "欺诈",
            "remark": "缺少二次确认",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_audit_export_downloads_xlsx():
    response = client.get("/api/v1/audit/logs/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content[:2] == b"PK"


def test_transaction_records_can_be_queried():
    response = client.get("/api/v1/detect/transactions?limit=10")
    assert response.status_code == 200
    assert isinstance(response.json()["data"], list)


def test_user_appeal_links_to_review_case():
    detect_response = client.post(
        "/api/v1/detect/transaction",
        json={
            "transaction": {
                "user_id": "U2002",
                "amount": 368000,
                "channel": "私人转账",
                "device_id": "DEV-WINDOWS-PC",
                "merchant_id": "MCH-RISK-001",
                "counterparty_type": "对私转账（陌生人）",
                "location": "哈尔滨",
            }
        },
    )
    tx_id = detect_response.json()["data"]["transaction_id"]
    response = client.post(
        "/api/v1/cases/appeals",
        json={
            "transaction_id": tx_id,
            "user_id": "U2002",
            "reason": "本人真实交易，请人工复核。",
            "materials": ["交易凭证", "聊天记录截图"],
        },
    )
    assert response.status_code == 200
    appeal = response.json()["data"]
    assert appeal["transaction_id"] == tx_id
    assert appeal["status"] == "SUBMITTED"

    rows = client.get("/api/v1/cases/appealable-transactions?user_id=U2002").json()["data"]
    linked = next(item for item in rows if item["transaction_id"] == tx_id)
    assert linked["appeal"]["appeal_id"] == appeal["appeal_id"]


def test_security_check_returns_score():
    response = client.post(
        "/api/v1/security/check",
        json={
            "devices": [{"trusted": True}, {"trusted": False}],
            "mfa": {"sms_enabled": True, "face_enabled": False},
            "privacy_items": [{"weak": True}],
            "recent_logs": [],
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["score"] < 92
    assert data["recommendations"]
