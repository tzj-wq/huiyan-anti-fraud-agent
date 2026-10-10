"""ML 基线特征工程与训练流程测试（需 scikit-learn，缺失时自动跳过）。"""
import pytest

pytest.importorskip("sklearn")

from scripts.eval_common import DEFAULT_SEED, generate_dataset, run_pipeline, seed_eval_profiles, stratified_split
from scripts.ml_baseline import FEATURE_NAMES, build_matrices, extract_row, run_all_models
from app.core.database import SessionLocal
from app.modules.strategy.service import get_active_strategy


@pytest.fixture(scope="module")
def pipeline_results():
    db = SessionLocal()
    try:
        profiles, cases, blacklist_values = generate_dataset(seed=DEFAULT_SEED, n_total=800)
        seed_eval_profiles(db, profiles, blacklist_values)
        strategy = get_active_strategy(db)
        return run_pipeline(db, strategy, cases)
    finally:
        db.close()


def test_feature_names_exclude_identity():
    for forbidden in ("user_id", "device_id", "merchant_id", "ip_address", "transaction_id"):
        assert not any(forbidden in name for name in FEATURE_NAMES)


def test_extract_row_shape_and_values(pipeline_results):
    result = pipeline_results[0]
    row = extract_row(result.case["payload"], result.features)
    assert len(row) == len(FEATURE_NAMES)
    assert all(isinstance(value, float) for value in row)
    assert row[FEATURE_NAMES.index("blacklist_hit")] in (0.0, 1.0)


def test_split_is_stratified(pipeline_results):
    labels = [result.case["label"] for result in pipeline_results]
    train_idx, test_idx = stratified_split(labels, 0.3, 42)
    test_ratio = sum(1 for i in test_idx if labels[i] == "FRAUD") / len(test_idx)
    assert 0.45 <= test_ratio <= 0.55
    assert not set(train_idx) & set(test_idx)
    assert len(train_idx) + len(test_idx) == len(labels)


def test_run_all_models(pipeline_results):
    labels = [result.case["label"] for result in pipeline_results]
    train_idx, test_idx = stratified_split(labels, 0.3, 42)
    rows = run_all_models(pipeline_results, train_idx, test_idx)
    names = {row["name"] for row in rows}
    assert {"逻辑回归", "随机森林", "梯度提升（HistGB）", "孤立森林"} <= names
    for row in rows:
        for key in ("precision", "recall", "f1", "auc"):
            assert 0.0 <= row[key] <= 1.0, f"{row['name']}.{key}={row[key]}"
    logistic = next(row for row in rows if row["name"] == "逻辑回归")
    assert logistic["f1"] > 0.75, "逻辑回归应能从同源特征学到非平凡模式"


def test_build_matrices_shapes(pipeline_results):
    labels = [result.case["label"] for result in pipeline_results]
    train_idx, test_idx = stratified_split(labels, 0.3, 42)
    X_train, y_train, X_test, y_test = build_matrices(pipeline_results, train_idx, test_idx)
    assert X_train.shape[1] == len(FEATURE_NAMES)
    assert X_train.shape[0] == len(train_idx)
    assert X_test.shape[0] == len(test_idx)
    assert set(y_train.tolist()) <= {0, 1}
