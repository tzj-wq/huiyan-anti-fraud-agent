"""离线评估（重构版）：多 Agent 协同决策引擎 vs 静态融合 / 最优单 Agent / 经典 ML 基线。

用法（在 backend/ 目录下）：
    python scripts/evaluate.py                    # 规则对比 + 消融 + 故障注入 + 延迟
    pip install -r scripts/requirements-eval.txt  # 可选：启用 ML 基线行

数据集：eval_common.generate_dataset 生成 4000 笔防泄漏标注交易（确定性），
分层 70/30 划分，主对比表全部方法在同一测试集上报 Precision / Recall / F1 / AUC。
最优单 Agent 在训练集上选择、测试集上报（避免测试集选择偏差）。
规则系统的 AUC 基于连续融合分（不含仲裁升级与一票否决，见报告注记）。

输出：scripts/eval_report.md 与控制台。
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_DB = BACKEND_ROOT / "huiyan_eval.db"
if EVAL_DB.exists():
    EVAL_DB.unlink()

os.environ["APP_ENV"] = "eval"
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DB}"
os.environ["LLM_ENABLED"] = "false"

from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.modules.detection.agents import AGENTS  # noqa: E402
from app.modules.detection.collaboration import (  # noqa: E402
    ArbitrationVerdict,
    analyze_conflict,
    arbitrate,
    decide,
    fuse,
)
from app.modules.detection.graph_workflow import _degraded_output  # noqa: E402
from app.modules.detection.service import _collaborative_decide, _feature_bundle  # noqa: E402
from app.modules.strategy.service import get_active_strategy  # noqa: E402
from scripts.eval_common import (  # noqa: E402
    DEFAULT_SEED,
    auc_score,
    dataset_audit,
    generate_dataset,
    label_scenarios,
    prf,
    run_pipeline,
    seed_eval_profiles,
    single_agent_decisions,
    static_fusion_decision,
    static_fusion_score,
    stratified_split,
)

N_TOTAL = 4000
TEST_SIZE = 0.3
SPLIT_SEED = 42
LATENCY_SAMPLE_STRIDE = 8


# ---------------------------------------------------------------------------
# 消融：基于缓存 outputs 的逐模块关闭
# ---------------------------------------------------------------------------

def ablation_no_confidence_weighting(result, strategy) -> str:
    """融合时置信度恒为 1.0（退化为策略权重算术平均），保留剔除与升级。"""
    verdict = result.verdict
    override = ArbitrationVerdict(
        triggered=verdict.triggered,
        trigger_reason=verdict.trigger_reason,
        adjusted_confidence={output.agent_id: 1.0 for output in result.outputs},
        excluded_agents=verdict.excluded_agents,
        escalation=verdict.escalation,
        rationale=verdict.rationale,
        method=verdict.method,
    )
    fusion = fuse(result.outputs, strategy.agent_weights, override)
    return decide(result.outputs, fusion, override, strategy)


def ablation_no_arbitration(result, strategy) -> str:
    """关闭仲裁层：无升级、无置信度调整，仅保留降级 Agent 剔除。"""
    override = ArbitrationVerdict(
        triggered=result.report.needs_arbitration,
        trigger_reason=result.report.trigger_reason,
        adjusted_confidence={output.agent_id: output.confidence for output in result.outputs},
        excluded_agents=result.report.degraded_agents,
        escalation="NONE",
        rationale="消融：关闭仲裁层",
        method="ablation",
    )
    fusion = fuse(result.outputs, strategy.agent_weights, override)
    return decide(result.outputs, fusion, override, strategy)


def ablation_blanket_escalation(result, strategy) -> str:
    """保留融合与置信度调整，但任何冲突一律升级（等价 v1.2 的冲突转人工规则），
    用于隔离"选择性升级"对精度的贡献。"""
    verdict = result.verdict
    escalation = "ESCALATE_REVIEW" if result.report.has_conflict else verdict.escalation
    override = ArbitrationVerdict(
        triggered=verdict.triggered,
        trigger_reason=verdict.trigger_reason,
        adjusted_confidence=verdict.adjusted_confidence,
        excluded_agents=verdict.excluded_agents,
        escalation=escalation,
        rationale=verdict.rationale,
        method=verdict.method,
    )
    fusion = fuse(result.outputs, strategy.agent_weights, override)
    return decide(result.outputs, fusion, override, strategy)


def ablation_leave_one_out(result, strategy, agent_id: str) -> str:
    """剔除单个 Agent 后重跑冲突分析→仲裁→融合（权重重归一化）。"""
    subset = [output for output in result.outputs if output.agent_id != agent_id]
    weights = strategy.agent_weights
    remaining = sum(weight for aid, weight in weights.items() if aid != agent_id) or 1.0
    renormalized = {aid: weight / remaining for aid, weight in weights.items() if aid != agent_id}
    report = analyze_conflict(subset, strategy)
    if report.needs_arbitration:
        verdict = arbitrate(result.case["payload"], subset, report, strategy, llm_client=None)
    else:
        verdict = ArbitrationVerdict.not_triggered()
    fusion = fuse(subset, renormalized, verdict)
    return decide(subset, fusion, verdict, strategy)


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------

def fmt_metrics(metrics: dict) -> str:
    return f"{metrics['precision']:.3f} / {metrics['recall']:.3f} / {metrics['f1']:.3f} / {metrics['fp']} / {metrics['fn']}"


def main() -> None:
    init_db()
    db = SessionLocal()
    strategy = get_active_strategy(db)

    print(f"[1/7] 生成数据集（{N_TOTAL} 笔，seed={DEFAULT_SEED}）...")
    profiles, cases, blacklist_values = generate_dataset(seed=DEFAULT_SEED, n_total=N_TOTAL)
    seed_eval_profiles(db, profiles, blacklist_values)
    audit = dataset_audit(cases)

    print("[2/7] 运行两阶段协同决策管线（规则仲裁）...")
    results = run_pipeline(db, strategy, cases)
    label_scenarios(results)

    labels = [case["label"] for case in cases]
    train_idx, test_idx = stratified_split(labels, TEST_SIZE, SPLIT_SEED)
    train_results = [results[i] for i in train_idx]
    test_results = [results[i] for i in test_idx]
    y_test = [1 if result.case["label"] == "FRAUD" else 0 for result in test_results]

    # --- 最优单 Agent：训练集选择，测试集上报（降级 Agent 无有效意见，不参与） ---
    print("[3/7] 单 Agent / 静态融合 / 两阶段协同指标...")
    best_agent_id, best_train_f1 = None, -1.0
    for agent in AGENTS:
        decisions = [single_agent_decisions(r.outputs, strategy).get(agent.agent_id) for r in train_results]
        if any(d is None for d in decisions):
            continue
        train_pairs = [(r.case["label"], decisions[i]) for i, r in enumerate(train_results)]
        f1 = prf(train_pairs)["f1"]
        if f1 > best_train_f1:
            best_agent_id, best_train_f1 = agent.agent_id, f1
    per_agent_test = {}
    for agent in AGENTS:
        decisions = [single_agent_decisions(r.outputs, strategy).get(agent.agent_id) for r in test_results]
        if any(d is None for d in decisions):
            continue
        test_pairs = [(r.case["label"], decisions[i]) for i, r in enumerate(test_results)]
        per_agent_test[agent.agent_id] = prf(test_pairs)

    static_pairs = [(r.case["label"], static_fusion_decision(r.outputs, strategy)) for r in test_results]
    two_pairs = [(r.case["label"], r.decision) for r in test_results]
    static_metrics = prf(static_pairs)
    two_metrics = prf(two_pairs)
    best_single_metrics = per_agent_test[best_agent_id]

    auc_static = auc_score(y_test, [static_fusion_score(r.outputs, strategy) for r in test_results])
    auc_two = auc_score(y_test, [r.fusion.risk_score for r in test_results])
    auc_best_single = auc_score(
        y_test,
        [next(o.risk_score for o in r.outputs if o.agent_id == best_agent_id) for r in test_results],
    )

    # --- ML 基线（可选依赖，缺失时报告标注） ---
    print("[4/7] 经典 ML 基线（scikit-learn / xgboost）...")
    ml_models = None
    ml_note = ""
    try:
        from scripts.ml_baseline import run_all_models

        ml_models = run_all_models(results, train_idx, test_idx)
    except ImportError as exc:
        ml_note = f"未运行（依赖未安装：{exc.name}；`pip install -r scripts/requirements-eval.txt` 后重跑）"

    # --- 消融 ---
    print("[5/7] 逐模块消融实验...")
    ablation_pairs = {
        "两阶段协同（全量）": two_pairs,
        "−置信度加权": [(r.case["label"], ablation_no_confidence_weighting(r, strategy)) for r in test_results],
        "−选择性升级（冲突一律升级）": [(r.case["label"], ablation_blanket_escalation(r, strategy)) for r in test_results],
        "−仲裁层（无升级与降权）": [(r.case["label"], ablation_no_arbitration(r, strategy)) for r in test_results],
        "−冲突分析（=静态加权）": static_pairs,
    }
    for agent in AGENTS:
        ablation_pairs[f"−{agent.agent_id}（leave-one-out）"] = [
            (r.case["label"], ablation_leave_one_out(r, strategy, agent.agent_id)) for r in test_results
        ]
    ablation_metrics = {name: prf(pairs) for name, pairs in ablation_pairs.items()}
    full_f1 = ablation_metrics["两阶段协同（全量）"]["f1"]

    # --- 故障注入 ---
    print("[6/7] 故障注入（确定性降级 1-2 个 Agent）...")
    fault_static, fault_two = [], []
    agreement_static = agreement_two = 0
    faultable = [agent.agent_id for agent in AGENTS if agent.agent_id != "semantic-analysis"]
    for index, result in enumerate(test_results):
        degraded_ids = {faultable[index % len(faultable)]}
        if index % 3 == 0:
            degraded_ids.add(faultable[(index + 2) % len(faultable)])
        faulted = [
            _degraded_output(output.agent_id, output.agent_type) if output.agent_id in degraded_ids else output
            for output in result.outputs
        ]
        fault_static.append((result.case["label"], static_fusion_decision(faulted, strategy)))
        report = analyze_conflict(faulted, strategy)
        verdict = arbitrate(result.case["payload"], faulted, report, strategy, llm_client=None)
        fusion = fuse(faulted, strategy.agent_weights, verdict)
        fault_two.append((result.case["label"], decide(faulted, fusion, verdict, strategy)))
        agreement_static += fault_static[-1][1] == static_pairs[index][1]
        agreement_two += fault_two[-1][1] == two_pairs[index][1]
    fault_static_metrics = prf(fault_static)
    fault_two_metrics = prf(fault_two)

    # --- 分场景 ---
    scenario_stats: dict[str, dict[str, int]] = {}
    for (label, static_pred), (_, two_pred), result in zip(static_pairs, two_pairs, test_results):
        scenario = result.case["scenario"]
        bucket = scenario_stats.setdefault(scenario, {"total": 0, "static_positive": 0, "two_positive": 0})
        bucket["total"] += 1
        bucket["static_positive"] += static_pred != "PASS"
        bucket["two_positive"] += two_pred != "PASS"

    # --- 延迟（并行管线抽样，纯决策不含 DB 持久化） ---
    print("[7/7] 决策引擎延迟测量...")
    latency_ms = []
    for result in results[::LATENCY_SAMPLE_STRIDE]:
        features = _feature_bundle(db, result.case["payload"])
        started = time.perf_counter()
        _collaborative_decide(result.case["payload"], features, strategy)
        latency_ms.append((time.perf_counter() - started) * 1000)
    latency_avg = statistics.mean(latency_ms)
    latency_p99 = sorted(latency_ms)[int(len(latency_ms) * 0.99) - 1]

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------
    lines: list[str] = []
    lines.append("# 慧眼识诈协同决策引擎离线评估报告")
    lines.append("")
    lines.append(f"- 数据集：{audit['total']} 笔确定性生成标注交易（FRAUD {audit['n_fraud']} / LEGIT {audit['n_legit']}），"
                 f"分层 70/30 划分（测试集 {len(test_results)} 笔），LLM 关闭、规则仲裁")
    lines.append("- 阳性定义：决策为 REVIEW 或 BLOCK；单 Agent 在训练集上选择、测试集上报")
    lines.append("- AUC 口径：规则系统取连续融合分（静态=算术加权分，两阶段=置信度加权融合分，"
                 "不含仲裁升级与一票否决），分类器取预测概率")
    lines.append("")

    lines.append("## 1. 数据集与防泄漏审计")
    lines.append("")
    lines.append("| 单特征 | AUC |")
    lines.append("|---|---|")
    for name, value in sorted(audit["feature_aucs"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {name} | {value:.3f} |")
    lines.append("")
    lines.append(f"- 金额重叠：欺诈小额（<2 万）占比 {audit['fraud_small_pct']:.1%}（试探型），"
                 f"正常大额（>30 万）占比 {audit['legit_large_pct']:.1%}——金额不是判别捷径")
    lines.append(f"- 黑名单：仅覆盖 {audit['blacklist_fraud_pct']:.0%} 的欺诈，正常交易命中 0 笔")
    lines.append(f"- 身份-标签独立性（偏离基率最大值）：user {audit['worst_user_deviation']:.3f} / "
                 f"merchant {audit['worst_merchant_deviation']:.3f} / device（类型内）{audit['worst_device_type_deviation']:.3f}")
    lines.append(f"- 结构子人群：{audit['regime_counts']}")
    lines.append("")

    lines.append("## 2. 主对比（同一测试集）")
    lines.append("")
    lines.append("| 决策模式 | Precision | Recall | F1 | AUC |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| 静态加权融合（v1.2 旧逻辑） | {static_metrics['precision']:.3f} | {static_metrics['recall']:.3f} | {static_metrics['f1']:.3f} | {auc_static:.3f} |")
    lines.append(f"| **两阶段协同（本版本）** | **{two_metrics['precision']:.3f}** | **{two_metrics['recall']:.3f}** | **{two_metrics['f1']:.3f}** | {auc_two:.3f} |")
    lines.append(f"| 最优单 Agent（{best_agent_id}，训练集选择） | {best_single_metrics['precision']:.3f} | {best_single_metrics['recall']:.3f} | {best_single_metrics['f1']:.3f} | {auc_best_single:.3f} |")
    if ml_models:
        for row in ml_models:
            suffix = f"（{row['note']}）" if row.get("note") else ""
            lines.append(f"| {row['name']}{suffix} | {row['precision']:.3f} | {row['recall']:.3f} | {row['f1']:.3f} | {row['auc']:.3f} |")
    else:
        lines.append(f"| ML 基线 | {ml_note} | | | |")
    lines.append("")
    lines.append("各 Agent 单独决策明细（测试集，P / R / F1 / 误报 / 漏报）：")
    lines.append("")
    for agent_id, metrics in sorted(per_agent_test.items(), key=lambda kv: -kv[1]["f1"]):
        lines.append(f"- {agent_id}：{fmt_metrics(metrics)}")
    lines.append("")

    lines.append("## 3. 逐模块消融（测试集）")
    lines.append("")
    lines.append("| 配置 | Precision | Recall | F1 | ΔF1 |")
    lines.append("|---|---|---|---|---|")
    for name, metrics in ablation_metrics.items():
        delta = metrics["f1"] - full_f1
        lines.append(f"| {name} | {metrics['precision']:.3f} | {metrics['recall']:.3f} | {metrics['f1']:.3f} | {delta:+.3f} |")
    lines.append("")

    lines.append("## 4. 故障注入（确定性降级 1-2 个 Agent，测试集）")
    lines.append("")
    lines.append("| 决策模式 | Precision | Recall | F1 | 误报 | 漏报 | 与无故障决策一致率 |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(f"| 静态加权融合（降级注入 0.8 分） | {fault_static_metrics['precision']:.3f} | {fault_static_metrics['recall']:.3f} | {fault_static_metrics['f1']:.3f} | {fault_static_metrics['fp']} | {fault_static_metrics['fn']} | {agreement_static / len(test_results):.1%} |")
    lines.append(f"| **两阶段协同（降级剔除+法定人数）** | **{fault_two_metrics['precision']:.3f}** | **{fault_two_metrics['recall']:.3f}** | **{fault_two_metrics['f1']:.3f}** | {fault_two_metrics['fp']} | {fault_two_metrics['fn']} | **{agreement_two / len(test_results):.1%}** |")
    lines.append("")

    lines.append("## 5. 分场景阳性率（静态融合 → 两阶段协同，测试集）")
    lines.append("")
    lines.append("| 场景 | 样本 | 静态阳性 | 协同阳性 | 说明 |")
    lines.append("|---|---|---|---|---|")
    scenario_notes = {
        "conflict": "Agent 意见分歧显著（spread > 阈值）",
        "borderline": "融合分处于复核阈值边界带",
        "clear": "各 Agent 意见一致",
    }
    for scenario, bucket in scenario_stats.items():
        note = scenario_notes.get(scenario, "")
        lines.append(f"| {scenario} | {bucket['total']} | {bucket['static_positive']} | {bucket['two_positive']} | {note} |")
    lines.append("")

    lines.append("## 6. 决策引擎延迟（并行管线抽样，纯决策不含 DB 持久化）")
    lines.append("")
    lines.append(f"- 平均：{latency_avg:.2f} ms，P99：{latency_p99:.2f} ms（{len(latency_ms)} 笔抽样）")
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("cd backend")
    lines.append("python scripts/evaluate.py                    # 本报告")
    lines.append("python scripts/calibrate.py                  # 数据集/指标快速校准")
    lines.append("python scripts/evaluate_llm.py               # LLM-as-Judge 仲裁对比（需 LLM_API_KEY）")
    lines.append("pip install -r scripts/requirements-eval.txt # ML 基线依赖（可选）")
    lines.append("```")

    report = "\n".join(lines)
    output_path = Path(__file__).resolve().parent / "eval_report.md"
    output_path.write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"\n报告已写入 {output_path}")

    db.close()
    engine.dispose()
    if EVAL_DB.exists():
        EVAL_DB.unlink()


if __name__ == "__main__":
    main()
