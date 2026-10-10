from fastapi.testclient import TestClient

from app.main import app

ADMIN = {"Authorization": "Bearer demo-admin-token"}
CLIENT = {"Authorization": "Bearer demo-client-token"}


def test_detect_response_contains_collaboration_trace(api_client):
    response = api_client.post(
        "/api/v1/detect/transaction",
        headers=ADMIN,
        json={
            "transaction": {
                "transaction_id": "TX-COLLAB-PASS",
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
    collab = data["collaboration"]
    assert collab["rounds"][0]["name"] == "独立评估"
    assert len(collab["rounds"][0]["agents"]) == 6
    assert all("confidence" in agent for agent in collab["rounds"][0]["agents"])
    assert all("confidence" in agent for agent in data["agent_results"])
    assert collab["fusion"]["final_score"] == data["risk_score"]
    assert collab["stage_ms"]["total_ms"] >= collab["stage_ms"]["stage1_ms"]


def test_conflict_transaction_triggers_arbitration_and_passes(api_client):
    response = api_client.post(
        "/api/v1/detect/transaction",
        headers=ADMIN,
        json={
            "transaction": {
                "transaction_id": "TX-COLLAB-CONFLICT",
                "user_id": "U3003",
                "amount": 3000,
                "channel": "私人转账",
                "device_id": "DEV-2002",
                "merchant_id": "MCH-NORMAL-001",
                "location": "北京",
                "night_operation": True,
            }
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["decision"] == "PASS"
    assert data["conflict_flag"] == 1
    rounds = data["collaboration"]["rounds"]
    assert len(rounds) == 2
    assert rounds[1]["name"] == "冲突仲裁"
    assert rounds[1]["method"] == "rule"
    assert rounds[1]["rationale"]
    assert rounds[1]["adjustments"]


def test_decision_process_endpoint_roundtrip(api_client):
    detect = api_client.post(
        "/api/v1/detect/transaction",
        headers=ADMIN,
        json={
            "transaction": {
                "transaction_id": "TX-COLLAB-PROCESS",
                "user_id": "U2002",
                "amount": 800000,
                "channel": "私人转账",
                "device_id": "DEV-WINDOWS-PC",
                "merchant_id": "MCH-RISK-001",
                "counterparty_type": "对私转账（陌生人）",
                "location": "哈尔滨",
            }
        },
    )
    assert detect.json()["data"]["decision"] in {"REVIEW", "BLOCK"}

    response = api_client.get("/api/v1/detect/decisions/TX-COLLAB-PROCESS/process", headers=ADMIN)
    assert response.status_code == 200
    process = response.json()["data"]
    assert process["transaction_id"] == "TX-COLLAB-PROCESS"
    assert process["total_rounds"] >= 1
    assert process["stages"]["rounds"][0]["agents"][0]["agent_id"]
    assert process["total_ms"] >= 0

    missing = api_client.get("/api/v1/detect/decisions/TX-NOT-EXIST/process", headers=ADMIN)
    assert missing.status_code == 404


def test_decision_process_scoped_for_client_role(api_client):
    denied = api_client.get("/api/v1/detect/decisions/TX-DEMO-CONFLICT/process", headers=CLIENT)
    assert denied.status_code == 403

    allowed = api_client.get("/api/v1/detect/decisions/TX-DEMO-REVIEW/process", headers=CLIENT)
    assert allowed.status_code == 200


def test_review_feedback_feeds_learning_and_adoption_flow(api_client):
    detect = api_client.post(
        "/api/v1/detect/transaction",
        headers=ADMIN,
        json={
            "transaction": {
                "transaction_id": "TX-LEARN-INTEGRATION",
                "user_id": "U2002",
                "amount": 900000,
                "channel": "私人转账",
                "device_id": "DEV-WINDOWS-PC",
                "merchant_id": "MCH-RISK-001",
                "counterparty_type": "对私转账（陌生人）",
                "location": "哈尔滨",
            }
        },
    )
    tx_id = detect.json()["data"]["transaction_id"]

    cases = api_client.get("/api/v1/cases", headers=ADMIN).json()["data"]
    target = next(case for case in cases if case["transaction"]["transaction_id"] == tx_id)
    review = api_client.post(
        "/api/v1/cases/review",
        headers=ADMIN,
        json={
            "case_id": target["case_id"],
            "review_result": "欺诈",
            "remark": "集成测试复核",
            "confirm_token": "demo-confirm",
        },
    )
    assert review.status_code == 200

    learning = api_client.get("/api/v1/strategies/learning", headers=ADMIN).json()["data"]
    assert any(agent["total_samples"] >= 1 for agent in learning["agents"])
    assert all("learned_weight" in agent and "configured_weight" in agent for agent in learning["agents"])

    adopt = api_client.post("/api/v1/strategies/adopt-learned", headers=ADMIN, json={"confirm_token": "demo-confirm"})
    assert adopt.status_code == 200
    adopted = adopt.json()["data"]
    assert abs(sum(adopted["agent_weights"].values()) - 1.0) < 0.01
    assert adopted["version"]

    without_token = api_client.post("/api/v1/strategies/adopt-learned", headers=ADMIN, json={})
    assert without_token.status_code == 400

    operator = TestClient(app)
    operator.headers.update({"Authorization": "Bearer demo-operator-token"})
    denied = operator.post("/api/v1/strategies/adopt-learned", json={"confirm_token": "demo-confirm"})
    assert denied.status_code == 403


def test_learning_endpoint_role_gated(api_client):
    ok = api_client.get("/api/v1/strategies/learning", headers=ADMIN)
    assert ok.status_code == 200
    denied = api_client.get("/api/v1/strategies/learning", headers=CLIENT)
    assert denied.status_code == 403
