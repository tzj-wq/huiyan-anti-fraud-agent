"""经典 ML 基线：与多 Agent 协同引擎在同一数据集/划分上的监督学习对照。

特征与 Agent 可观测信息同源（payload + feature_bundle 派生特征），
禁止使用 user_id/device_id/merchant_id 等身份原始值，防止模型记忆身份。
依赖 scikit-learn（可选 xgboost），通过 requirements-eval.txt 安装。
"""
from __future__ import annotations

import math

CHANNELS = ["APP", "WEB", "网络平台", "线下当面交易", "私人转账", "其他渠道"]
COUNTERPARTIES = ["对私转账（陌生人）", "个人卖家", "对私转账（熟人）", "网络电商", "对公转账", ""]

FEATURE_NAMES = [
    "amount",
    "log1p_amount",
    "amount_gt_300k",
    "night",
    "unusual_location",
    "device_risky",
    "device_windows",
    "device_iphone",
    "shared_device_count",
    "risk_graph_hops",
    "merchant_risky",
    "blacklist_hit",
    "list_fields_checked",
    "has_profile",
    *(f"channel={value}" for value in CHANNELS),
    *(f"counterparty={value or '缺失'}" for value in COUNTERPARTIES),
]


def extract_row(payload: dict, features: dict) -> list[float]:
    amount = float(payload.get("amount") or 0)
    device_id = str(payload.get("device_id", ""))
    location = str(payload.get("location", ""))
    home = str(features.get("last_login_location", ""))
    row = [
        amount,
        math.log1p(amount),
        1.0 if amount > 300000 else 0.0,
        1.0 if payload.get("night_operation") else 0.0,
        1.0 if location and location != home else 0.0,
        1.0 if device_id.endswith("X") else 0.0,
        1.0 if "WINDOWS" in device_id.upper() else 0.0,
        1.0 if "IPHONE" in device_id.upper() else 0.0,
        float(features.get("shared_device_count", 0)),
        float(features.get("risk_graph_hops", 0)),
        1.0 if payload.get("merchant_id") == "MCH-RISK-001" else 0.0,
        1.0 if features.get("blacklist_hit") else 0.0,
        float(features.get("list_fields_checked", 0)),
        1.0 if features.get("has_profile") else 0.0,
    ]
    channel = str(payload.get("channel", ""))
    row.extend(1.0 if channel == value else 0.0 for value in CHANNELS)
    counterparty = str(payload.get("counterparty_type", ""))
    row.extend(1.0 if counterparty == value else 0.0 for value in COUNTERPARTIES)
    return row


def build_matrices(results, train_idx, test_idx):
    import numpy as np

    X = np.array([extract_row(r.case["payload"], r.features) for r in results], dtype=float)
    y = np.array([1 if r.case["label"] == "FRAUD" else 0 for r in results], dtype=int)
    return X[train_idx], y[train_idx], X[test_idx], y[test_idx]


def _metrics(y_true, y_pred, y_score) -> dict:
    from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "auc": float(roc_auc_score(y_true, y_score)),
    }


def run_all_models(results, train_idx, test_idx) -> list[dict]:
    X_train, y_train, X_test, y_test = build_matrices(results, train_idx, test_idx)
    rows: list[dict] = []

    from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    logistic = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42))
    logistic.fit(X_train, y_train)
    rows.append({"name": "逻辑回归", **_metrics(y_test, logistic.predict(X_test), logistic.predict_proba(X_test)[:, 1])})

    forest = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1)
    forest.fit(X_train, y_train)
    rows.append({"name": "随机森林", **_metrics(y_test, forest.predict(X_test), forest.predict_proba(X_test)[:, 1])})

    boosting = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=42)
    boosting.fit(X_train, y_train)
    rows.append({"name": "梯度提升（HistGB）", **_metrics(y_test, boosting.predict(X_test), boosting.predict_proba(X_test)[:, 1])})

    try:
        from xgboost import XGBClassifier
    except ImportError:
        XGBClassifier = None
    if XGBClassifier is not None:
        xgb = XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, eval_metric="logloss", random_state=42,
        )
        xgb.fit(X_train, y_train)
        rows.append({"name": "XGBoost", **_metrics(y_test, xgb.predict(X_test), xgb.predict_proba(X_test)[:, 1])})

    def isolation_row(contamination, note):
        model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42, n_jobs=-1)
        model.fit(X_train)
        anomaly_score = -model.decision_function(X_test)
        y_pred = (model.predict(X_test) == -1).astype(int)
        return {
            "name": "孤立森林",
            "note": note,
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "auc": float(roc_auc_score(y_test, anomaly_score)),
        }

    rows.append(isolation_row("auto", "无监督"))
    rows.append(isolation_row(float(y_train.mean()), "oracle 污染率，仅参考"))
    return rows
