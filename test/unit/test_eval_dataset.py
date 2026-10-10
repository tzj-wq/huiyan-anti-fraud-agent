"""评估数据集防泄漏与确定性测试（无 sklearn 依赖，CI 默认环境可跑）。"""
import pytest

from scripts.eval_common import (
    DEFAULT_SEED,
    dataset_audit,
    generate_dataset,
    run_pipeline,
    seed_eval_profiles,
)
from app.modules.detection.service import _feature_bundle
from app.modules.strategy.service import get_active_strategy


@pytest.fixture(scope="module")
def dataset():
    # 与正式评估同规模（n=4000）：身份平衡断言在小样本下统计噪声过大
    profiles, cases, blacklist_values = generate_dataset(seed=DEFAULT_SEED, n_total=4000)
    return profiles, cases, blacklist_values


@pytest.fixture(scope="module")
def audit(dataset):
    _, cases, _ = dataset
    return dataset_audit(cases)


def test_deterministic_same_seed():
    profiles_a, cases_a, blacklist_a = generate_dataset(seed=DEFAULT_SEED, n_total=400)
    profiles_b, cases_b, blacklist_b = generate_dataset(seed=DEFAULT_SEED, n_total=400)
    assert profiles_a == profiles_b
    assert blacklist_a == blacklist_b
    for case_a, case_b in zip(cases_a, cases_b):
        assert case_a["label"] == case_b["label"]
        assert case_a["payload"] == case_b["payload"]
        assert case_a["derived"] == case_b["derived"]


def test_different_seed_differs():
    _, cases_a, _ = generate_dataset(seed=DEFAULT_SEED, n_total=400)
    _, cases_b, _ = generate_dataset(seed=DEFAULT_SEED + 1, n_total=400)
    assert any(a["payload"] != b["payload"] for a, b in zip(cases_a, cases_b))


def test_class_balance(audit):
    assert audit["total"] == 4000
    assert 0.48 <= audit["fraud_ratio"] <= 0.52


def test_single_feature_auc_capped(audit):
    for name, value in audit["feature_aucs"].items():
        assert value <= 0.85, f"{name} AUC={value:.3f} 超上限，存在单特征捷径"


def test_amount_overlap(audit):
    assert audit["fraud_small_pct"] >= 0.08, "欺诈应含小额试探"
    assert audit["legit_large_pct"] >= 0.03, "正常应含大额转账"
    assert audit["feature_aucs"]["amount"] <= 0.85


def test_blacklist_coverage(audit, dataset):
    _, cases, _ = dataset
    assert 0.08 <= audit["blacklist_fraud_pct"] <= 0.12
    assert audit["legit_blacklist_hits"] == 0
    for case in cases:
        if case["derived"]["blacklist_hit"]:
            assert case["label"] == "FRAUD"


def test_identity_label_independence(audit, dataset):
    assert audit["worst_user_deviation"] <= 0.20
    assert audit["worst_merchant_deviation"] <= 0.20
    assert audit["worst_device_type_deviation"] <= 0.20


def test_users_appear_in_both_classes(dataset):
    _, cases, _ = dataset
    by_user = {}
    for case in cases:
        user_id = case["payload"]["user_id"]
        if user_id.startswith("UBLK"):
            continue
        by_user.setdefault(user_id, set()).add(case["label"])
    both = sum(1 for labels in by_user.values() if labels == {"FRAUD", "LEGIT"})
    assert both / len(by_user) >= 0.95, "同一用户应在两类标签中交叉出现"


def test_weak_alarm_regime_is_legit(dataset):
    _, cases, _ = dataset
    weak = [case for case in cases if case["regime"] == "weak_alarm"]
    assert weak, "弱告警子人群不应为空"
    for case in weak:
        assert case["label"] == "LEGIT"
        assert case["payload"]["night_operation"] is True


def test_seed_eval_profiles_and_feature_bundle(dataset, db_session):
    profiles, cases, blacklist_values = dataset
    seed_eval_profiles(db_session, profiles, blacklist_values)

    hit_case = next(case for case in cases if case["derived"]["blacklist_hit"])
    features = _feature_bundle(db_session, hit_case["payload"])
    assert features["blacklist_hit"] is True

    normal_case = next(
        case
        for case in cases
        if not case["derived"]["blacklist_hit"]
        and case["payload"]["user_id"] in {p["user_id"] for p in profiles if p["has_profile"]}
    )
    features = _feature_bundle(db_session, normal_case["payload"])
    assert features["blacklist_hit"] is False
    assert features["has_profile"] is True


def test_run_pipeline_smoke(dataset, db_session):
    profiles, cases, blacklist_values = dataset
    seed_eval_profiles(db_session, profiles, blacklist_values)
    strategy = get_active_strategy(db_session)
    results = run_pipeline(db_session, strategy, cases[:12])
    assert len(results) == 12
    for result in results:
        assert result.decision in {"PASS", "REVIEW", "BLOCK"}
        assert len(result.outputs) == 6
        assert 0 <= result.fusion.risk_score <= 1
