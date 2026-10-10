from app.modules.detection.agents import (
    ListMatchAgent,
    TransactionAnalysisAgent,
    clamp_score,
    stable_noise,
)


def test_clamp_score_keeps_scores_inside_supported_range():
    assert clamp_score(-2) == 0.01
    assert clamp_score(2) == 0.99
    assert clamp_score(0.45678) == 0.4568


def test_stable_noise_is_deterministic_for_same_transaction():
    transaction = {
        "transaction_id": "TX-UNIT-001",
        "user_id": "U1001",
        "amount": 1280,
        "channel": "APP",
        "device_id": "DEV-1001",
        "merchant_id": "MCH-NORMAL-001",
        "location": "Shanghai",
    }

    first = stable_noise(transaction, "list-match")
    second = stable_noise(transaction, "list-match")

    assert first == second
    assert -0.035 <= first <= 0.035


def test_list_match_agent_marks_blacklist_hits_as_high_risk():
    output = ListMatchAgent().analyze(
        {"user_id": "U9009", "amount": 1000, "channel": "WEB"},
        {"blacklist_hit": True},
    )

    assert output.risk_label == "BLACKLIST_HIT"
    assert output.risk_score > 0.85
    assert output.exec_time_ms >= 1


def test_transaction_analysis_scores_large_amount_above_small_amount():
    agent = TransactionAnalysisAgent()
    small = agent.analyze(
        {"transaction_id": "TX-SMALL", "amount": 300, "channel": "APP"},
        {},
    )
    large = agent.analyze(
        {"transaction_id": "TX-LARGE", "amount": 900000, "channel": "APP"},
        {},
    )

    assert large.risk_score > small.risk_score
    assert large.risk_label == "LARGE_AMOUNT"
