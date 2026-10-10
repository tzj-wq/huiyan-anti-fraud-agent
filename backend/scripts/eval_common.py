"""离线评估共享库：防泄漏数据集生成器、度量函数与决策管线封装。

数据集设计目标（讨论见 docs/DESIGN_DECISIONS.md）：
- 标签由金额/对象/设备/行为/渠道/图关联多个维度的信号组合决定，
  任何单一特征都无法单独高精度预测标签（单特征 AUC 上限约束）；
- 身份字段（user/merchant/device）在两类标签中交叉出现，其判别力只能
  来自可观测派生特征（设备类型、商户风险、名单命中），不依赖身份记忆；
- 金额分布两类重叠：欺诈含小额试探，正常含大额转账；
- 黑名单只覆盖少数欺诈（一票否决路径的真实占比）；
- 全程 random.Random(seed) 驱动，确定性可复现。

本模块不依赖 sklearn/numpy（ML 基线见 ml_baseline.py）。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sqlalchemy import select

from app.models import RiskListItem, UserProfile
from app.modules.detection.agents import AGENTS
from app.modules.detection.collaboration import (
    ArbitrationVerdict,
    analyze_conflict,
    arbitrate,
    decide,
    fuse,
)
from app.modules.detection.service import _feature_bundle

DEFAULT_SEED = 20250901
N_USERS = 600
N_BLACKLIST_IDENTITIES = 60
DEVICE_POOLS = {"risk_x": 40, "windows": 40, "android": 60, "iphone": 60}
MERCHANT_POOLS = {"ecommerce": 30, "corp": 30, "normal": 19}
RISK_MERCHANT = "MCH-RISK-001"

CITIES = [
    "上海", "北京", "深圳", "广州", "杭州", "成都", "武汉", "南京", "重庆", "西安",
    "苏州", "天津", "长沙", "郑州", "青岛", "大连", "厦门", "合肥", "福州", "昆明",
    "沈阳", "哈尔滨", "石家庄", "太原", "南昌", "贵阳", "南宁", "长春", "济南", "兰州",
]

# 条件分布：FRAUD 与 LEGIT 在各维度上重叠但存在系统性偏移。
DISTRIBUTIONS = {
    "FRAUD": {
        "amount_regimes": [
            ("probe", 0.14, math.log(2000), 1.0),
            ("large", 0.86, math.log(240000), 1.0),
        ],
        "channel": {"私人转账": 0.58, "其他渠道": 0.06, "WEB": 0.12, "APP": 0.09, "网络平台": 0.08, "线下当面交易": 0.07},
        "counterparty": {"对私转账（陌生人）": 0.68, "个人卖家": 0.14, "对私转账（熟人）": 0.07, "网络电商": 0.07, "对公转账": 0.04},
        "counterparty_missing": 0.04,
        "night": 0.68,
        "unusual": 0.87,
        "device_type": {"risk_x": 0.54, "windows": 0.20, "android": 0.15, "iphone": 0.11},
        "merchant_risky": 0.46,
    },
    "LEGIT": {
        "amount_regimes": [
            ("daily", 0.82, math.log(8000), 1.3),
            ("large", 0.15, math.log(165000), 0.5),
            ("super", 0.03, math.log(700000), 0.45),
        ],
        "channel": {"APP": 0.32, "网络平台": 0.24, "线下当面交易": 0.19, "WEB": 0.10, "私人转账": 0.09, "其他渠道": 0.06},
        "counterparty": {"对私转账（陌生人）": 0.028, "个人卖家": 0.13, "对私转账（熟人）": 0.18, "网络电商": 0.34, "对公转账": 0.272},
        "counterparty_missing": 0.06,
        "night": 0.18,
        "unusual": 0.30,
        "device_type": {"risk_x": 0.016, "windows": 0.17, "android": 0.384, "iphone": 0.43},
        "merchant_risky": 0.02,
        # 结构性子人群：无画像用户的夜间异地小额转账——行为 Agent 高分但
        # 低置信（无画像基线），是"低置信弱告警应放行"的代表场景。
        "weak_alarm_rate": 0.10,
    },
}
DEFAULT_BLACKLIST_FRAUD_RATIO = 0.10


# ---------------------------------------------------------------------------
# 数据集生成（纯函数，不触 DB）
# ---------------------------------------------------------------------------

def _lognormal(rng: random.Random, mu: float, sigma: float, lo: float = 100.0, hi: float = 2_000_000.0) -> int:
    return int(round(max(lo, min(hi, rng.lognormvariate(mu, sigma)))))


def _pick(rng: random.Random, weights: dict) -> str:
    total = sum(weights.values())
    roll = rng.random() * total
    acc = 0.0
    for key, weight in weights.items():
        acc += weight
        if roll <= acc:
            return key
    return next(iter(weights))


def _pick_amount(rng: random.Random, regimes: list) -> tuple[str, int]:
    name = _pick(rng, {name: prob for name, prob, _, _ in regimes})
    for regime_name, _, mu, sigma in regimes:
        if regime_name == name:
            return name, _lognormal(rng, mu, sigma)
    raise AssertionError(name)


def _build_pools(rng: random.Random) -> dict:
    users = [
        {
            "user_id": f"U{i:05d}",
            "home": rng.choice(CITIES),
            "risk_level": rng.choice(["LOW", "MEDIUM", "HIGH"]),
            "has_profile": rng.random() < 0.70,
        }
        for i in range(N_USERS)
    ]
    blacklist_users = [
        {
            "user_id": f"UBLK{i:03d}",
            "home": rng.choice(CITIES),
            "risk_level": "HIGH",
            "has_profile": True,
        }
        for i in range(N_BLACKLIST_IDENTITIES)
    ]
    devices = {
        "risk_x": [f"DEV-RX-{i:03d}X" for i in range(DEVICE_POOLS["risk_x"])],
        "windows": [f"DEV-WIN-{i:03d}-WINDOWS" for i in range(DEVICE_POOLS["windows"])],
        "android": [f"DEV-AND-{i:03d}" for i in range(DEVICE_POOLS["android"])],
        "iphone": [f"DEV-IPHONE-{i:03d}" for i in range(DEVICE_POOLS["iphone"])],
    }
    blacklist_devices = [f"DEV-BLKX-{i:03d}X" for i in range(N_BLACKLIST_IDENTITIES)]
    normal_merchants = (
        [f"MCH-ECOMMERCE-{i:03d}" for i in range(MERCHANT_POOLS["ecommerce"])]
        + [f"MCH-CORP-{i:03d}" for i in range(MERCHANT_POOLS["corp"])]
        + [f"MCH-NORMAL-{i:03d}" for i in range(MERCHANT_POOLS["normal"])]
    )
    return {
        "users": users,
        "blacklist_users": blacklist_users,
        "devices": devices,
        "blacklist_devices": blacklist_devices,
        "normal_merchants": normal_merchants,
    }


def generate_dataset(
    seed: int = DEFAULT_SEED,
    n_total: int = 4000,
    fraud_ratio: float = 0.5,
    blacklist_fraud_ratio: float = DEFAULT_BLACKLIST_FRAUD_RATIO,
) -> tuple[list[dict], list[dict], set]:
    """生成标注数据集。

    返回 (profiles, cases, blacklist_values)：
    - profiles: 用户画像列表（has_profile=False 的用户不写入 DB，走 payload.home_location 回退）
    - cases: [{label, regime, payload, derived}]
    - blacklist_values: 需写入 RiskListItem 的 user_id/device_id 集合
    """
    rng = random.Random(seed)
    pools = _build_pools(rng)

    n_fraud = round(n_total * fraud_ratio)
    labels = ["FRAUD"] * n_fraud + ["LEGIT"] * (n_total - n_fraud)
    rng.shuffle(labels)

    fraud_pos = [i for i, value in enumerate(labels) if value == "FRAUD"]
    legit_pos = [i for i, value in enumerate(labels) if value == "LEGIT"]
    blacklist_idx = set(rng.sample(fraud_pos, round(n_fraud * blacklist_fraud_ratio)))
    weak_alarm_idx = set(
        rng.sample(legit_pos, round(len(legit_pos) * DISTRIBUTIONS["LEGIT"]["weak_alarm_rate"]))
    )

    def make_balanced_picker(pool_ids: list[str]):
        """贪心均衡分配：优先补齐该标签计数最少的身份，保证身份-标签独立。"""
        counts = {pid: [0, 0] for pid in pool_ids}

        def pick(label: str) -> str:
            label_index = 0 if label == "FRAUD" else 1
            chosen = min(pool_ids, key=lambda pid: (counts[pid][label_index], counts[pid][0] + counts[pid][1], pid))
            counts[chosen][label_index] += 1
            return chosen

        return pick

    user_picker = make_balanced_picker([user["user_id"] for user in pools["users"]])
    no_profile_users = [user for user in pools["users"] if not user["has_profile"]]
    weak_user_picker = make_balanced_picker([user["user_id"] for user in no_profile_users])
    merchant_picker = make_balanced_picker(pools["normal_merchants"])
    device_pickers = {dtype: make_balanced_picker(ids) for dtype, ids in pools["devices"].items()}
    bl_user_cycle = 0
    bl_device_cycle = 0
    bl_toggle = 0
    user_by_id = {user["user_id"]: user for user in pools["users"] + pools["blacklist_users"]}
    cases: list[dict] = []

    for index, label in enumerate(labels):
        dist = DISTRIBUTIONS[label]
        regime = "standard"
        if index in blacklist_idx:
            regime = "blacklist"
        elif index in weak_alarm_idx:
            regime = "weak_alarm"

        blacklist_hit = False
        if regime == "blacklist":
            # 黑名单命中一半走用户名单、一半走设备名单，均属 FRAUD
            bl_toggle += 1
            blacklist_hit = True
            if bl_toggle % 2 == 1:
                user = pools["blacklist_users"][bl_user_cycle % len(pools["blacklist_users"])]
                bl_user_cycle += 1
                device_type = _pick(rng, dist["device_type"])
                device_id = device_pickers[device_type]("FRAUD")
            else:
                user = user_by_id[user_picker("FRAUD")]
                device_type = "risk_x"
                device_id = pools["blacklist_devices"][bl_device_cycle % len(pools["blacklist_devices"])]
                bl_device_cycle += 1
        elif regime == "weak_alarm":
            user = user_by_id[weak_user_picker(label)]
            device_type = _pick(rng, dist["device_type"])
            device_id = device_pickers[device_type](label)
        else:
            user = user_by_id[user_picker(label)]
            device_type = _pick(rng, dist["device_type"])
            device_id = device_pickers[device_type](label)

        if rng.random() < dist["merchant_risky"]:
            merchant_id = RISK_MERCHANT
        else:
            merchant_id = merchant_picker(label)

        amount_regime, amount = _pick_amount(rng, dist["amount_regimes"])
        channel = _pick(rng, dist["channel"])
        if rng.random() < dist["counterparty_missing"]:
            counterparty = ""
        else:
            counterparty = _pick(rng, dist["counterparty"])
        night = rng.random() < dist["night"]
        unusual = rng.random() < dist["unusual"]

        if regime == "weak_alarm":
            channel = "私人转账"
            night = True
            unusual = True
            counterparty = "个人卖家" if rng.random() < 0.5 else "对私转账（熟人）"
            amount_regime, amount = "daily", _lognormal(rng, math.log(8000), 1.2)

        home = user["home"]
        if unusual:
            location = rng.choice([city for city in CITIES if city != home])
        else:
            location = home

        payload = {
            "transaction_id": f"TX-EVAL-{index:05d}",
            "user_id": user["user_id"],
            "amount": amount,
            "channel": channel,
            "device_id": device_id,
            "merchant_id": merchant_id,
            "counterparty_type": counterparty,
            "location": location,
            "night_operation": night,
        }
        if not user["has_profile"]:
            payload["home_location"] = home

        cases.append(
            {
                "label": label,
                "regime": regime,
                "payload": payload,
                "derived": {
                    "unusual_location": unusual,
                    "blacklist_hit": blacklist_hit,
                    "device_type": device_type,
                    "merchant_risky": merchant_id == RISK_MERCHANT,
                    "amount_regime": amount_regime,
                },
            }
        )

    profiles = pools["users"] + pools["blacklist_users"]
    blacklist_values = {user["user_id"] for user in pools["blacklist_users"]} | set(pools["blacklist_devices"])
    return profiles, cases, blacklist_values


# ---------------------------------------------------------------------------
# 度量（stdlib 实现，无 sklearn 依赖）
# ---------------------------------------------------------------------------

def prf(results: list[tuple[str, str]]) -> dict:
    tp = sum(1 for label, pred in results if label == "FRAUD" and pred != "PASS")
    fn = sum(1 for label, pred in results if label == "FRAUD" and pred == "PASS")
    fp = sum(1 for label, pred in results if label == "LEGIT" and pred != "PASS")
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "fp": fp, "fn": fn}


def auc_score(y_true: list[int], y_score: list[float]) -> float:
    """Mann-Whitney U（平均秩处理并列）。"""
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if not n_pos or not n_neg:
        return 0.5
    order = sorted(range(len(y_score)), key=lambda i: y_score[i])
    ranks = [0.0] * len(order)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and y_score[order[j + 1]] == y_score[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    pos_rank_sum = sum(ranks[i] for i in range(len(y_true)) if y_true[i] == 1)
    return (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def single_feature_auc(cases: list[dict], feature_fn) -> float:
    y_true = [1 if case["label"] == "FRAUD" else 0 for case in cases]
    y_score = [float(feature_fn(case)) for case in cases]
    return auc_score(y_true, y_score)


FEATURE_FNS = {
    "amount": lambda case: case["payload"]["amount"],
    "对私陌生人": lambda case: 1 if case["payload"]["counterparty_type"] == "对私转账（陌生人）" else 0,
    "风险设备(X结尾)": lambda case: 1 if case["payload"]["device_id"].endswith("X") else 0,
    "风险商户": lambda case: case["derived"]["merchant_risky"],
    "夜间交易": lambda case: 1 if case["payload"]["night_operation"] else 0,
    "异地交易": lambda case: 1 if case["derived"]["unusual_location"] else 0,
    "私人转账渠道": lambda case: 1 if case["payload"]["channel"] == "私人转账" else 0,
    "黑名单命中": lambda case: 1 if case["derived"]["blacklist_hit"] else 0,
}


def dataset_audit(cases: list[dict]) -> dict:
    """防泄漏与平衡审计：单特征 AUC、金额重叠、黑名单覆盖、身份平衡。"""
    n_fraud = sum(1 for case in cases if case["label"] == "FRAUD")
    fraud_small = sum(1 for case in cases if case["label"] == "FRAUD" and case["payload"]["amount"] < 20000)
    legit_large = sum(1 for case in cases if case["label"] == "LEGIT" and case["payload"]["amount"] > 300000)

    feature_aucs = {name: single_feature_auc(cases, fn) for name, fn in FEATURE_FNS.items()}

    def label_stats(extract_id, min_count=4):
        stats: dict[str, list[int]] = {}
        for case in cases:
            identity = extract_id(case)
            if identity is None:
                continue
            bucket = stats.setdefault(identity, [0, 0])
            bucket[0 if case["label"] == "FRAUD" else 1] += 1
        return {identity: counts for identity, counts in stats.items() if sum(counts) >= min_count}

    user_stats = label_stats(
        lambda case: case["payload"]["user_id"]
        if not case["payload"]["user_id"].startswith("UBLK")
        else None
    )
    merchant_stats = label_stats(lambda case: case["payload"]["merchant_id"] if case["payload"]["merchant_id"] != RISK_MERCHANT else None)
    # 正常商户池的类别基率（风险商户分流了部分欺诈案），平衡口径为相对基率偏差
    merchant_base = [0, 0]
    for case in cases:
        if case["payload"]["merchant_id"] != RISK_MERCHANT:
            merchant_base[0 if case["label"] == "FRAUD" else 1] += 1
    merchant_base_share = merchant_base[0] / sum(merchant_base) if sum(merchant_base) else 0.5

    # 设备：同一类型的设备池被两类按不同比例使用（类型本身是可观测信号），
    # 因此平衡口径是"设备占比偏离其类型基率"，而非偏离全局 0.5。
    device_type_stats: dict[str, list[int]] = {}
    for case in cases:
        if case["payload"]["device_id"].startswith("DEV-BLKX"):
            continue
        dtype = case["derived"]["device_type"]
        bucket = device_type_stats.setdefault(dtype, [0, 0])
        bucket[0 if case["label"] == "FRAUD" else 1] += 1
    device_by_id: dict[str, list[int]] = {}
    for case in cases:
        device_id = case["payload"]["device_id"]
        if device_id.startswith("DEV-BLKX"):
            continue
        bucket = device_by_id.setdefault(device_id, [0, 0])
        bucket[0 if case["label"] == "FRAUD" else 1] += 1
    worst_device_type_deviation = 0.0
    for device_id, counts in device_by_id.items():
        dtype = "risk_x" if device_id.endswith("X") and device_id.startswith("DEV-RX") else (
            "windows" if "WINDOWS" in device_id else ("iphone" if "IPHONE" in device_id else "android")
        )
        type_base = device_type_stats.get(dtype)
        if type_base is None or sum(type_base) == 0 or sum(counts) < 4:
            continue
        base_share = type_base[0] / sum(type_base)
        worst_device_type_deviation = max(worst_device_type_deviation, abs(counts[0] / sum(counts) - base_share))

    return {
        "total": len(cases),
        "n_fraud": n_fraud,
        "n_legit": len(cases) - n_fraud,
        "fraud_ratio": n_fraud / len(cases) if cases else 0.0,
        "fraud_small_pct": fraud_small / n_fraud if n_fraud else 0.0,
        "legit_large_pct": legit_large / (len(cases) - n_fraud) if n_fraud != len(cases) else 0.0,
        "feature_aucs": feature_aucs,
        "blacklist_fraud_pct": sum(1 for case in cases if case["label"] == "FRAUD" and case["derived"]["blacklist_hit"]) / n_fraud if n_fraud else 0.0,
        "legit_blacklist_hits": sum(1 for case in cases if case["label"] == "LEGIT" and case["derived"]["blacklist_hit"]),
        "worst_user_deviation": max((abs(c[0] / sum(c) - 0.5) for c in user_stats.values()), default=0.0),
        "worst_merchant_deviation": max((abs(c[0] / sum(c) - merchant_base_share) for c in merchant_stats.values()), default=0.0),
        "worst_device_type_deviation": worst_device_type_deviation,
        "regime_counts": {
            regime: sum(1 for case in cases if case["regime"] == regime)
            for regime in ("standard", "blacklist", "weak_alarm")
        },
    }


# ---------------------------------------------------------------------------
# 决策模式与管线
# ---------------------------------------------------------------------------

def single_agent_decisions(outputs, strategy) -> dict[str, str]:
    """单 Agent 独立决策。降级 Agent 无有效风险意见，不产生决策（评估上等同于缺席）。"""
    decisions = {}
    for output in outputs:
        if output.degraded:
            continue
        if output.risk_label == "BLACKLIST_HIT":
            decisions[output.agent_id] = "BLOCK"
        elif output.risk_score >= strategy.block_threshold:
            decisions[output.agent_id] = "BLOCK"
        elif output.risk_score >= strategy.review_threshold:
            decisions[output.agent_id] = "REVIEW"
        else:
            decisions[output.agent_id] = "PASS"
    return decisions


def _active_outputs(outputs) -> list:
    return [o for o in outputs if not o.degraded]


def static_fusion_score(outputs, strategy) -> float:
    """v1.2 静态基线：剔除降级 Agent 后按策略权重重归一化加权（等价无语义 Agent 的旧版）。"""
    active = _active_outputs(outputs)
    weights = strategy.agent_weights
    total = sum(float(weights.get(o.agent_id, 0.2)) for o in active)
    if not total:
        return 0.0
    weighted = sum(o.risk_score * float(weights.get(o.agent_id, 0.2)) for o in active)
    return weighted / total


def static_fusion_decision(outputs, strategy) -> str:
    """v1.2 旧逻辑：静态加权平均（冲突即 REVIEW），降级 Agent 剔除后重归一化。"""
    active = _active_outputs(outputs)
    score = static_fusion_score(outputs, strategy)
    scores = [o.risk_score for o in active]
    conflict = bool(scores and max(scores) - min(scores) > strategy.conflict_threshold)
    if score >= strategy.block_threshold or any(o.risk_label == "BLACKLIST_HIT" for o in active):
        return "BLOCK"
    if score >= strategy.review_threshold or conflict:
        return "REVIEW"
    return "PASS"


def stratified_split(labels: list[str], test_size: float = 0.3, seed: int = 42) -> tuple[list[int], list[int]]:
    """按标签分层划分，返回 (train_indices, test_indices)，确定性。"""
    rng = random.Random(seed)
    by_label: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(label, []).append(index)
    test_set: set[int] = set()
    for _, indices in sorted(by_label.items()):
        rng.shuffle(indices)
        test_set.update(indices[: round(len(indices) * test_size)])
    train = [index for index in range(len(labels)) if index not in test_set]
    return train, sorted(test_set)


@dataclass
class CaseResult:
    case: dict
    features: dict
    outputs: list
    report: object
    verdict: object
    fusion: object
    decision: str


def run_agents_serial(payload: dict, features: dict) -> list:
    """串行执行 Agent（与并行结果一致：stable_noise 是交易的确定性函数）。"""
    return sorted((agent.analyze(payload, features) for agent in AGENTS), key=lambda o: o.agent_id)


def run_pipeline(db, strategy, cases: list[dict]) -> list[CaseResult]:
    """对每笔交易跑完整两阶段管线（规则仲裁），缓存中间产物供消融/基线复用。"""
    results = []
    for case in cases:
        payload = case["payload"]
        features = _feature_bundle(db, payload)
        outputs = run_agents_serial(payload, features)
        report = analyze_conflict(outputs, strategy)
        if report.needs_arbitration:
            verdict = arbitrate(payload, outputs, report, strategy, llm_client=None)
        else:
            verdict = ArbitrationVerdict.not_triggered()
        fusion = fuse(outputs, strategy.agent_weights, verdict)
        decision = decide(outputs, fusion, verdict, strategy)
        results.append(CaseResult(case, features, outputs, report, verdict, fusion, decision))
    return results


def seed_eval_profiles(db, profiles: list[dict], blacklist_values: set) -> None:
    """把生成器的用户画像与黑名单写入评估库（不依赖 seed.py）。"""
    existing_users = {row.user_id for row in db.execute(select(UserProfile)).scalars()}
    user_rows = [
        UserProfile(
            user_id=profile["user_id"],
            account_name=f"eval-{profile['user_id']}",
            risk_level=profile["risk_level"],
            last_login_location=profile["home"],
        )
        for profile in profiles
        if profile["has_profile"] and profile["user_id"] not in existing_users
    ]
    db.add_all(user_rows)
    existing_items = {row.item_value for row in db.execute(select(RiskListItem)).scalars()}
    item_rows = []
    for offset, value in enumerate(sorted(blacklist_values)):
        if value in existing_items:
            continue
        list_type = "USER" if value.startswith("U") else "DEVICE"
        item_rows.append(
            RiskListItem(
                item_id=f"RL-EVAL-{offset:04d}",
                list_type=list_type,
                item_value=value,
                risk_level="L3",
                description="评估数据集黑名单",
                source="eval",
            )
        )
    db.add_all(item_rows)
    db.commit()


def label_scenarios(results: list[CaseResult]) -> None:
    """按仲裁触发原因做数据驱动场景打标。"""
    mapping = {"CONFLICT": "conflict", "BORDERLINE": "borderline"}
    for result in results:
        result.case["scenario"] = mapping.get(result.report.trigger_reason, "clear")
