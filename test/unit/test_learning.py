import math

from app.models import AgentPerformance
from app.modules.detection.service import detect_transaction
from app.modules.strategy.learning import (
    EWMA_ALPHA,
    MIN_READY_SAMPLES,
    PRIOR_ACCURACY,
    SHRINKAGE_K,
    compute_learned_weights,
    correctness_signal,
    get_learning_stats,
    record_feedback,
    shrunk_accuracy,
)
from app.modules.strategy.service import DEFAULT_WEIGHTS

FRAUD_PAYLOAD = {
    "user_id": "U1001",
    "amount": 900000,
    "channel": "APP",
    "device_id": "DEV-1001",
    "merchant_id": "MCH-NORMAL-001",
    "location": "上海",
}


def _reset_performance(db):
    db.query(AgentPerformance).delete()
    db.commit()


def test_correctness_signal_fraud_direction():
    assert correctness_signal(0.75, "FRAUD", 0.6) == 1
    assert correctness_signal(0.30, "FRAUD", 0.6) == 0


def test_correctness_signal_false_positive_direction():
    assert correctness_signal(0.30, "FALSE_POSITIVE", 0.6) == 1
    assert correctness_signal(0.75, "FALSE_POSITIVE", 0.6) == 0
    assert correctness_signal(0.20, "LEGIT", 0.6) == 1


def test_shrinkage_pulls_small_samples_to_prior():
    perf = type("Perf", (), {"total_samples": 1, "correct_ewma": 0.4})()
    shrunk = shrunk_accuracy(perf)
    assert math.isclose(shrunk, (1 * 0.4 + SHRINKAGE_K * PRIOR_ACCURACY) / (1 + SHRINKAGE_K))
    # 小样本时收缩值应明显靠近先验而非样本值
    assert abs(shrunk - PRIOR_ACCURACY) < abs(0.4 - PRIOR_ACCURACY)

    many = type("Perf", (), {"total_samples": 200, "correct_ewma": 0.4})()
    assert abs(shrunk_accuracy(many) - 0.4) < 0.05


def test_record_feedback_updates_ewma_and_weights(db_session):
    _reset_performance(db_session)
    detect_transaction(db_session, {"transaction_id": "TX-LEARN-1", **FRAUD_PAYLOAD}, "TR-LEARN")
    for label in ["FRAUD", "FRAUD", "FALSE_POSITIVE"]:
        record_feedback(db_session, transaction_id="TX-LEARN-1", label=label, trace_id="TR-LEARN")

    stats = get_learning_stats(db_session)
    by_agent = {agent["agent_id"]: agent for agent in stats["agents"]}
    assert set(by_agent) == set(DEFAULT_WEIGHTS)

    # 交易分析 Agent 在该场景高分（两次 FRAUD 判对），第三次误报标签下高分记为错误信号
    ewma_after_two_fraud = EWMA_ALPHA + (1 - EWMA_ALPHA) * (EWMA_ALPHA + (1 - EWMA_ALPHA) * PRIOR_ACCURACY)
    expected = (1 - EWMA_ALPHA) * ewma_after_two_fraud
    assert abs(by_agent["transaction-analysis"]["correct_ewma"] - expected) < 0.02
    assert by_agent["transaction-analysis"]["total_samples"] == 3
    assert len(by_agent["transaction-analysis"]["recent_history"]) == 3

    weights = compute_learned_weights(db_session)
    assert abs(sum(weights.values()) - 1.0) < 0.01
    # 降级剔除的 Agent（LLM 关闭时的语义 Agent）不产生学习信号，权重集合为配置集合的子集
    assert weights and set(weights) <= set(DEFAULT_WEIGHTS)
    assert all(value > 0 for value in weights.values())


def test_learning_stats_cold_start(db_session):
    _reset_performance(db_session)
    stats = get_learning_stats(db_session)
    assert not stats["ready"]
    for agent in stats["agents"]:
        assert agent["total_samples"] == 0
        assert agent["correct_ewma"] is None
        # 冷启动时学习权重回退为当前生效的配置权重（可能已被历史采纳更新）
        assert agent["learned_weight"] == agent["configured_weight"]


def test_learning_ready_threshold(db_session):
    _reset_performance(db_session)
    for index in range(MIN_READY_SAMPLES):
        tx_id = f"TX-READY-{index}"
        detect_transaction(db_session, {"transaction_id": tx_id, **FRAUD_PAYLOAD}, f"TR-{tx_id}")
        record_feedback(db_session, transaction_id=tx_id, label="FRAUD", trace_id=f"TR-{tx_id}")
    stats = get_learning_stats(db_session)
    assert stats["ready"]
    active = [agent for agent in stats["agents"] if agent["total_samples"] > 0]
    assert len(active) >= 3
    assert all(agent["total_samples"] >= MIN_READY_SAMPLES for agent in active)


def test_softmax_weight_spread_is_gradual(db_session):
    """温度与收缩的组合应产生温和的权重分化，而非赢者通吃。"""
    _reset_performance(db_session)
    for index in range(10):
        tx_id = f"TX-SPREAD-{index}"
        detect_transaction(db_session, {"transaction_id": tx_id, **FRAUD_PAYLOAD}, f"TR-{tx_id}")
        record_feedback(db_session, transaction_id=tx_id, label="FRAUD", trace_id=f"TR-{tx_id}")
    weights = compute_learned_weights(db_session)
    # 该场景下只有交易分析 Agent 持续判对，其权重最高但不吞并全部权重
    assert max(weights, key=weights.get) == "transaction-analysis"
    assert max(weights.values()) < 0.6
    assert min(weights.values()) > 0.05
