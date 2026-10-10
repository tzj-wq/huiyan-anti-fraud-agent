"""快速校准通道：数据集分布参数 → 各决策模式指标摘要（秒级，不写报告）。

用法（backend/ 目录下）：
    python scripts/calibrate.py [--seed N] [--n N] [--fraud-ratio R] [--blacklist-ratio R]

校准目标：
    0.80 <= best_single_f1 <= 0.90（单 Agent 上限受控）
    two_stage_f1 >= 0.92 且 - static_f1 >= 0.03 且 - best_single_f1 >= 0.02
    单特征 AUC 全部 <= 0.85；conflict 案件充足
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CALIBRATE_DB = BACKEND_ROOT / "huiyan_calibrate.db"
if CALIBRATE_DB.exists():
    CALIBRATE_DB.unlink()

os.environ["APP_ENV"] = "calibrate"
os.environ["DATABASE_URL"] = f"sqlite:///{CALIBRATE_DB}"
os.environ["LLM_ENABLED"] = "false"

from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.modules.strategy.service import get_active_strategy  # noqa: E402
from scripts.eval_common import (  # noqa: E402
    dataset_audit,
    generate_dataset,
    label_scenarios,
    prf,
    run_pipeline,
    seed_eval_profiles,
    single_agent_decisions,
    static_fusion_decision,
)


def quantiles(values: list[float]) -> str:
    if not values:
        return "-"
    ordered = sorted(values)
    p10 = ordered[int(len(ordered) * 0.10)]
    p50 = ordered[int(len(ordered) * 0.50)]
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.90))]
    return f"p10={p10:.3f} p50={p50:.3f} p90={p90:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20250901)
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--fraud-ratio", type=float, default=0.5)
    parser.add_argument("--blacklist-ratio", type=float, default=0.10)
    args = parser.parse_args()

    profiles, cases, blacklist_values = generate_dataset(
        seed=args.seed, n_total=args.n, fraud_ratio=args.fraud_ratio, blacklist_fraud_ratio=args.blacklist_ratio
    )
    audit = dataset_audit(cases)
    print(f"数据集 {audit['total']} 笔（FRAUD {audit['n_fraud']} / LEGIT {audit['n_legit']}），regime={audit['regime_counts']}")
    print("单特征 AUC：")
    for name, value in audit["feature_aucs"].items():
        flag = "  <-- 超上限!" if value > 0.85 else ""
        print(f"  {name:<14} {value:.3f}{flag}")
    print(
        f"金额重叠：FRAUD<2w {audit['fraud_small_pct']:.1%} / LEGIT>30w {audit['legit_large_pct']:.1%}；"
        f"黑名单覆盖 FRAUD {audit['blacklist_fraud_pct']:.1%} / LEGIT 命中 {audit['legit_blacklist_hits']}"
    )
    print(
        f"身份平衡（偏离基率最大值）：user {audit['worst_user_deviation']:.3f} / "
        f"merchant {audit['worst_merchant_deviation']:.3f} / device(类型内) {audit['worst_device_type_deviation']:.3f}"
    )

    init_db()
    db = SessionLocal()
    seed_eval_profiles(db, profiles, blacklist_values)
    strategy = get_active_strategy(db)
    results = run_pipeline(db, strategy, cases)
    label_scenarios(results)

    per_agent: dict[str, list[tuple[str, str]]] = {}
    for result in results:
        for agent_id, pred in single_agent_decisions(result.outputs, strategy).items():
            per_agent.setdefault(agent_id, []).append((result.case["label"], pred))
    agent_metrics = {agent_id: prf(pairs) for agent_id, pairs in per_agent.items()}
    best_agent = max(agent_metrics, key=lambda a: agent_metrics[a]["f1"])
    print("\n各 Agent 单独决策（阈值 P/R/F1/FP/FN）：")
    for agent_id, metrics in sorted(agent_metrics.items(), key=lambda kv: -kv[1]["f1"]):
        print(f"  {agent_id:<22} {metrics['precision']:.3f} / {metrics['recall']:.3f} / {metrics['f1']:.3f} / {metrics['fp']} / {metrics['fn']}")

    static_results = [(r.case["label"], static_fusion_decision(r.outputs, strategy)) for r in results]
    two_results = [(r.case["label"], r.decision) for r in results]
    static_metrics = prf(static_results)
    two_metrics = prf(two_results)
    best_single = agent_metrics[best_agent]
    print(f"\nbest-single（{best_agent}）: F1={best_single['f1']:.3f} (FP={best_single['fp']} FN={best_single['fn']})")
    print(f"静态加权融合: F1={static_metrics['f1']:.3f} P={static_metrics['precision']:.3f} R={static_metrics['recall']:.3f} (FP={static_metrics['fp']} FN={static_metrics['fn']})")
    print(f"两阶段协同:  F1={two_metrics['f1']:.3f} P={two_metrics['precision']:.3f} R={two_metrics['recall']:.3f} (FP={two_metrics['fp']} FN={two_metrics['fn']})")

    triggers: dict[str, int] = {}
    scenarios: dict[str, int] = {}
    for result in results:
        triggers[result.report.trigger_reason] = triggers.get(result.report.trigger_reason, 0) + 1
        scenarios[result.case["scenario"]] = scenarios.get(result.case["scenario"], 0) + 1
    print(f"仲裁触发：{triggers}")
    print(f"场景分布：{scenarios}")

    print("\n融合分分布（两阶段 fusion.risk_score）：")
    print(f"  FRAUD {quantiles([r.fusion.risk_score for r in results if r.case['label'] == 'FRAUD'])}")
    print(f"  LEGIT {quantiles([r.fusion.risk_score for r in results if r.case['label'] == 'LEGIT'])}")

    fp_attr: dict[str, int] = {}
    for result in results:
        if result.case["label"] == "LEGIT" and result.decision != "PASS":
            derived = result.case["derived"]
            if result.case["payload"]["amount"] > 300000:
                tag = "大额转账(>30w)"
            elif result.case["payload"]["device_id"].endswith("X"):
                tag = "风险设备"
            elif result.case["payload"]["counterparty_type"] == "对私转账（陌生人）":
                tag = "陌生对象"
            elif derived["merchant_risky"]:
                tag = "风险商户"
            elif result.case["regime"] == "weak_alarm":
                tag = "弱告警(低置信行为)"
            else:
                tag = "其他"
            fp_attr[tag] = fp_attr.get(tag, 0) + 1
    fn_attr: dict[str, int] = {}
    for result in results:
        if result.case["label"] == "FRAUD" and result.decision == "PASS":
            fn_attr[result.case["regime"]] = fn_attr.get(result.case["regime"], 0) + 1
    print(f"\n两阶段误报归因：{fp_attr}")
    print(f"两阶段漏报复盘：{fn_attr}")

    ok = (
        0.80 <= best_single["f1"] <= 0.90
        and two_metrics["f1"] >= 0.92
        and two_metrics["f1"] - static_metrics["f1"] >= 0.03
        and two_metrics["f1"] - best_single["f1"] >= 0.02
        and all(v <= 0.85 for v in audit["feature_aucs"].values())
        and triggers.get("CONFLICT", 0) >= 60
    )
    print(f"\n校准目标达成：{'PASS' if ok else 'FAIL'}")

    db.close()
    engine.dispose()
    if CALIBRATE_DB.exists():
        CALIBRATE_DB.unlink()


if __name__ == "__main__":
    main()
