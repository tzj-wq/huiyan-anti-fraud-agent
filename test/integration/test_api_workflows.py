def test_health_endpoint_is_public(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_api_requires_bearer_token(api_client):
    response = api_client.get("/api/v1/audit/logs")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 401
    assert body["trace_id"].startswith("TR-")


def test_dashboard_metrics_flow_uses_seeded_demo_data(api_client):
    response = api_client.get(
        "/api/v1/dashboard/metrics",
        headers={"Authorization": "Bearer demo-admin-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kpis"]["transactions"] >= 2
    assert data["decision_distribution"]
    assert data["agent_latency"]


def test_low_risk_detection_flow_returns_pass_decision(api_client):
    response = api_client.post(
        "/api/v1/detect/transaction",
        headers={"Authorization": "Bearer demo-admin-token"},
        json={
            "transaction": {
                "transaction_id": "TX-INTEGRATION-PASS",
                "user_id": "U1001",
                "amount": 1200,
                "channel": "APP",
                "device_id": "DEV-1001",
                "merchant_id": "MCH-NORMAL-001",
                "location": "Shanghai",
            }
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["decision"] == "PASS"
    assert data["agent_count"] == 6
    assert data["transaction_id"] == "TX-INTEGRATION-PASS"


def test_blacklist_detection_creates_alert_and_case(api_client):
    response = api_client.post(
        "/api/v1/detect/transaction",
        headers={"Authorization": "Bearer demo-admin-token"},
        json={
            "transaction": {
                "transaction_id": "TX-INTEGRATION-BLOCK",
                "user_id": "U9009",
                "amount": 1240000,
                "channel": "WEB",
                "device_id": "DEV-RISK-X",
                "merchant_id": "MCH-RISK-001",
                "location": "Shanghai",
            }
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["decision"] == "BLOCK"
    assert data["alert"]["case_id"].startswith("CASE-")


def test_client_role_only_sees_own_transactions(api_client):
    response = api_client.get(
        "/api/v1/detect/transactions?limit=20",
        headers={"Authorization": "Bearer demo-client-token"},
    )

    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert all(row["user_id"] == "U2002" for row in rows)


def test_audit_export_downloads_xlsx(api_client):
    response = api_client.get(
        "/api/v1/audit/logs/export",
        headers={"Authorization": "Bearer demo-admin-token"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content[:2] == b"PK"
