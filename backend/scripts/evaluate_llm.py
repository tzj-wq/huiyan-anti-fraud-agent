"""LLM-as-Judge 仲裁真实评估：规则仲裁 vs 大模型仲裁在同一冲突子集上的对比。

用法（在 backend/ 目录下，需根目录 .env 配置 LLM_ENABLED=true 与 LLM_API_KEY）：
    python scripts/evaluate_llm.py [--limit 120] [--sleep 0.2]

流程：生成与 evaluate.py 相同的数据集 → 规则仲裁跑通两阶段管线 →
筛选触发仲裁（CONFLICT/BORDERLINE）的案件，按标签分层取样 →
每案按【生产 3s 预算】直调 LLM 裁决（测真实回退率）；超时/失败再以
【评估 15s 预算】重试一次（测裁决质量），与规则裁决对比最终决策。
注：temperature=0.2，结果为固定子集上的点估计；LLM 裁决经
_merge_llm_verdict 合并——安全基线（降级剔除与法定人数升级）不可被 LLM 降低。

输出：scripts/eval_llm_report.md 与控制台。
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_DB = BACKEND_ROOT / "huiyan_eval_llm.db"
if EVAL_DB.exists():
    EVAL_DB.unlink()

os.environ["APP_ENV"] = "llm_eval"
os.environ["DATABASE_URL"] = f"sqlite:///{EVAL_DB}"
# 不设置 LLM_ENABLED：由根目录 .env 提供真实 LLM 配置

import app.core.llm as llm_module  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal, engine, init_db  # noqa: E402
from app.core.llm import LLMClient  # noqa: E402
from app.modules.detection.collaboration import _merge_llm_verdict, decide, fuse, rule_arbitrate  # noqa: E402
from app.modules.strategy.service import get_active_strategy  # noqa: E402
from scripts.eval_common import (  # noqa: E402
    DEFAULT_SEED,
    generate_dataset,
    prf,
    run_pipeline,
    seed_eval_profiles,
)

N_TOTAL = 4000
SUBSET_TRIGGERS = {"CONFLICT", "BORDERLINE"}
PRODUCTION_BUDGET_S = 3.0   # 与 app/core/llm.py ARBITRATION_TIMEOUT_SECONDS 一致
EVAL_BUDGET_S = 15.0        # 评估模式放宽预算（推理模型思考耗时更长）


def call_with_budget(llm_client, payload, agent_payloads, conflict_analysis, budget_s):
    """按指定超时预算调用 LLM 仲裁（临时覆盖模块常量，不改生产代码）。"""
    original = llm_module.ARBITRATION_TIMEOUT_SECONDS
    llm_module.ARBITRATION_TIMEOUT_SECONDS = budget_s
    try:
        return llm_client.arbitrate_conflict(
            transaction=payload,
            agent_outputs=agent_payloads,
            conflict_analysis=conflict_analysis,
        )
    finally:
        llm_module.ARBITRATION_TIMEOUT_SECONDS = original


def build_agent_payloads(outputs):
    return [
        {
            "agent_id": output.agent_id,
            "risk_score": output.risk_score,
            "risk_label": output.risk_label,
            "confidence": output.confidence,
            "evidence": output.evidence[0]["summary"] if output.evidence else "",
        }
        for output in outputs
        if not output.degraded
    ]


def build_conflict_analysis(report):
    return {
        "spread": report.spread,
        "median_score": report.median_score,
        "high_deviants": report.high_deviants,
        "low_deviants": report.low_deviants,
        "degraded_agents": report.degraded_agents,
    }


def select_subset(results, per_class_limit):
    """按标签分层选取触发仲裁的案件（确定性排序）。"""
    by_label: dict[str, list] = {"FRAUD": [], "LEGIT": []}
    for result in results:
        if result.report.needs_arbitration and result.report.trigger_reason in SUBSET_TRIGGERS:
            by_label[result.case["label"]].append(result)
    subset = []
    for label in ("FRAUD", "LEGIT"):
        ordered = sorted(by_label[label], key=lambda r: r.case["payload"]["transaction_id"])
        subset.extend(ordered[:per_class_limit])
    return subset, {label: len(items) for label, items in by_label.items()}


def percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=120, help="子集规模上限（按标签对半分层）")
    parser.add_argument("--sleep", type=float, default=0.2, help="相邻 LLM 调用间隔秒数")
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.llm_enabled and settings.llm_api_key):
        print("LLM 未配置：请在项目根目录 .env 设置 LLM_ENABLED=true 与 LLM_API_KEY")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    strategy = get_active_strategy(db)
    profiles, cases, blacklist_values = generate_dataset(seed=DEFAULT_SEED, n_total=N_TOTAL)
    seed_eval_profiles(db, profiles, blacklist_values)

    print(f"[1/3] 运行规则仲裁管线（{N_TOTAL} 笔）...")
    results = run_pipeline(db, strategy, cases)
    subset, available = select_subset(results, args.limit // 2)
    if not subset:
        print("没有触发仲裁的案件，无法评估")
        sys.exit(1)
    print(f"触发仲裁案件：FRAUD {available['FRAUD']} / LEGIT {available['LEGIT']}，"
          f"分层取样 {len(subset)} 笔（每类上限 {args.limit // 2}）")

    llm_client = LLMClient()
    rule_pairs, llm_pairs = [], []
    change_matrix: dict[str, int] = {}
    latency_ms: list[float] = []
    parse_success = 0
    budget_success = 0
    fallback = 0
    improved = harmed = 0
    rationales: list[str] = []
    escalations = {"NONE": 0, "ESCALATE_REVIEW": 0, "ESCALATE_BLOCK": 0}

    print(f"[2/3] 逐案调用 LLM 仲裁（provider={settings.llm_provider}, model={settings.llm_model}，"
          f"生产预算 {PRODUCTION_BUDGET_S}s / 评估预算 {EVAL_BUDGET_S}s）...")
    for index, result in enumerate(subset):
        payload = result.case["payload"]
        outputs = result.outputs
        report = result.report
        rule_verdict = rule_arbitrate(outputs, report, strategy)
        rule_decision = decide(outputs, fuse(outputs, strategy.agent_weights, rule_verdict), rule_verdict, strategy)
        agent_payloads = build_agent_payloads(outputs)
        conflict_analysis = build_conflict_analysis(report)

        # 先按生产 3s 预算（测真实回退率），失败再按评估预算重试一次（测裁决质量）
        started = time.perf_counter()
        raw = call_with_budget(llm_client, payload, agent_payloads, conflict_analysis, PRODUCTION_BUDGET_S)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if isinstance(raw, dict):
            budget_success += 1
        else:
            started = time.perf_counter()
            raw = call_with_budget(llm_client, payload, agent_payloads, conflict_analysis, EVAL_BUDGET_S)
            elapsed_ms = (time.perf_counter() - started) * 1000

        if isinstance(raw, dict):
            parse_success += 1
            latency_ms.append(elapsed_ms)
            llm_verdict = _merge_llm_verdict(rule_verdict, raw, outputs, report) or rule_verdict
            if len(rationales) < 3 and raw.get("rationale"):
                rationales.append(str(raw["rationale"])[:80])
            raw_escalation = raw.get("escalation", "NONE")
            if raw_escalation in escalations:
                escalations[raw_escalation] += 1
        else:
            fallback += 1
            llm_verdict = rule_verdict

        llm_decision = decide(outputs, fuse(outputs, strategy.agent_weights, llm_verdict), llm_verdict, strategy)
        rule_pairs.append((result.case["label"], rule_decision))
        llm_pairs.append((result.case["label"], llm_decision))
        if rule_decision != llm_decision:
            change_matrix[f"{rule_decision}->{llm_decision}"] = change_matrix.get(f"{rule_decision}->{llm_decision}", 0) + 1
            rank = {"PASS": 0, "REVIEW": 1, "BLOCK": 2}
            if rank[llm_decision] > rank[rule_decision]:
                direction = "保守"
            else:
                direction = "宽松"
            if result.case["label"] == "FRAUD":
                improved += direction == "保守"
                harmed += direction == "宽松"
            else:
                improved += direction == "宽松"
                harmed += direction == "保守"

        if (index + 1) % 20 == 0 or index + 1 == len(subset):
            print(f"  进度 {index + 1}/{len(subset)}，成功 {parse_success}（生产预算内 {budget_success}），双预算均失败 {fallback}")
        time.sleep(args.sleep)

    rule_metrics = prf(rule_pairs)
    llm_metrics = prf(llm_pairs)
    agreement = sum(1 for (_, a), (_, b) in zip(rule_pairs, llm_pairs) if a == b) / len(subset)

    lines: list[str] = []
    lines.append("# LLM-as-Judge 冲突仲裁评估报告")
    lines.append("")
    lines.append(f"- 模型：{settings.llm_provider} / {settings.llm_model}（temperature=0.2，推理模型；"
                 f"生产预算 {PRODUCTION_BUDGET_S}s / 评估预算 {EVAL_BUDGET_S}s，失败自动回退规则仲裁）")
    lines.append(f"- 子集：{len(subset)} 笔触发仲裁的交易（CONFLICT/BORDERLINE），"
                 f"FRAUD {sum(1 for p in rule_pairs if p[0] == 'FRAUD')} / LEGIT {sum(1 for p in rule_pairs if p[0] == 'LEGIT')}，"
                 f"与主评估同一数据集（seed={DEFAULT_SEED}）")
    lines.append(f"- 决策一致率（规则 vs LLM 仲裁后最终决策）：{agreement:.1%}")
    lines.append("")
    lines.append("## 1. 仲裁效果对比（同一子集，对 ground truth）")
    lines.append("")
    lines.append("| 仲裁方式 | Precision | Recall | F1 | 误报 | 漏报 |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(f"| 规则仲裁 | {rule_metrics['precision']:.3f} | {rule_metrics['recall']:.3f} | {rule_metrics['f1']:.3f} | {rule_metrics['fp']} | {rule_metrics['fn']} |")
    lines.append(f"| LLM-as-Judge | {llm_metrics['precision']:.3f} | {llm_metrics['recall']:.3f} | {llm_metrics['f1']:.3f} | {llm_metrics['fp']} | {llm_metrics['fn']} |")
    lines.append("")
    lines.append("## 2. 决策改变分析")
    lines.append("")
    if change_matrix:
        for change, count in sorted(change_matrix.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {change}：{count} 笔")
    else:
        lines.append("- 无决策改变")
    lines.append(f"- 标签感知质量：改变且更正确 {improved} 笔 / 改变且更错误 {harmed} 笔")
    lines.append(f"- LLM 原始升级动作分布：{escalations}")
    lines.append("")
    lines.append("## 3. LLM 调用质量")
    lines.append("")
    lines.append(f"- 解析成功率（评估预算 {EVAL_BUDGET_S}s）：{parse_success / len(subset):.1%}（{parse_success}/{len(subset)}）")
    lines.append(f"- 生产预算（{PRODUCTION_BUDGET_S}s）内成功率：{budget_success / len(subset):.1%}（{budget_success}/{len(subset)}）"
                 f"——超出部分为超时自动回退规则仲裁，生产链路不受影响")
    lines.append(f"- 双预算均失败：{fallback} 笔")
    if latency_ms:
        lines.append(f"- 成功调用延迟：平均 {statistics.mean(latency_ms):.0f} ms / P50 {percentile(latency_ms, 0.5):.0f} ms / P99 {percentile(latency_ms, 0.99):.0f} ms")
    lines.append("")
    if rationales:
        lines.append("## 4. 仲裁理由样例")
        lines.append("")
        for rationale in rationales:
            lines.append(f"- {rationale}")
        lines.append("")
    lines.append("## 注记")
    lines.append("")
    lines.append("- temperature=0.2 下的点估计，复跑存在方差；子集与规则仲裁输入完全相同，对比公平")
    lines.append("- 安全基线：LLM 裁决经合并层约束——规则侧的升级结论不可被 LLM 降低，降级剔除与法定人数保护恒定生效")

    report = "\n".join(lines)
    output_path = Path(__file__).resolve().parent / "eval_llm_report.md"
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
