from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.core.llm import LLMClient
from app.main import app
from app.seed import seed_demo_data

# 测试确定性：全局关闭真实 LLM 调用（语义 Agent 降级、审核建议走规则回退），
# LLM 参与路径由独立用例局部 mock 验证。
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


def _detect_and_get_case_id(payload: dict) -> str:
    response = client.post("/api/v1/detect/transaction", json={"transaction": payload})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["alert"] is not None, "该交易未生成案件"
    return data["alert"]["case_id"]


def _review_case(case_id: str, result: str = "误报", remark: str = "测试复核") -> None:
    response = client.post(
        "/api/v1/cases/review",
        json={"case_id": case_id, "review_result": result, "remark": remark, "confirm_token": "demo-confirm"},
    )
    assert response.status_code == 200


def test_rag_index_after_review_and_search():
    """案件复核完成后自动入库 RAG，可按语义文本检索命中。"""
    case_id = _detect_and_get_case_id(
        {
            "user_id": "U9009",
            "amount": 1240000,
            "channel": "WEB",
            "device_id": "DEV-RISK-X",
            "merchant_id": "MCH-RISK-001",
            "location": "上海",
        }
    )
    _review_case(case_id)
    response = client.get(
        "/api/v1/review-assistant/cases/search",
        params={"q": "U9009 DEV-RISK-X WEB 误报"},
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items, "案例库检索结果为空"
    hit = next(item for item in items if item["case_id"] == case_id)
    assert hit["label"] == "FALSE_POSITIVE"
    assert hit["similarity"] > 0


def test_review_advice_uses_llm_when_available():
    """LLM 可用时，审核助手返回 LLM 结构化建议。"""
    case_id = _detect_and_get_case_id(
        {
            "user_id": "U1001",
            "amount": 900000,
            "channel": "APP",
            "device_id": "DEV-1001",
            "merchant_id": "MCH-NORMAL-001",
            "location": "上海",
        }
    )
    fake_advice = {
        "recommendation": "ESCALATE",
        "confidence": 0.85,
        "rationale": "相似案例显示大额异常交易多被确认，建议升级深度调查",
        "cited_cases": [],
    }
    with patch.object(LLMClient, "enabled", return_value=True), patch.object(
        LLMClient, "generate_review_advice", return_value=fake_advice
    ):
        response = client.post("/api/v1/review-assistant/advice", json={"case_id": case_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["case_id"] == case_id
    assert data["fallback"] is False
    assert data["advice"] == fake_advice
    assert isinstance(data["candidates"], list)


def test_review_advice_falls_back_when_llm_unavailable():
    """LLM 关闭时，审核助手回退规则模板，仍给出可执行建议。"""
    case_id = _detect_and_get_case_id(
        {
            "user_id": "U1001",
            "amount": 900000,
            "channel": "APP",
            "device_id": "DEV-1001",
            "merchant_id": "MCH-NORMAL-001",
            "location": "上海",
        }
    )
    response = client.post("/api/v1/review-assistant/advice", json={"case_id": case_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["fallback"] is True
    assert data["advice"]["recommendation"] in {"REVIEW_CONFIRM", "RELEASE", "ESCALATE"}
    assert 0.0 <= data["advice"]["confidence"] <= 1.0
    assert data["advice"]["rationale"]
