"""两阶段协同决策核心：冲突分析、仲裁、置信度加权融合。

流程：Stage1 各 Agent 并行独立评估（含置信度）→ ConflictAnalyzer 归因
→ 需要时触发 Stage2 仲裁（规则 / LLM 双模，输出同构 ArbitrationVerdict）
→ 置信度加权融合（降级 Agent 剔除而非注入保守分）→ 全程 trace 记录。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from app.modules.detection.agents import AgentOutput

DEVIATION_RATIO = 0.4
WEAK_CONFIDENCE = 0.6
STRONG_DISSENT_CONFIDENCE = 0.75
BORDERLINE_BAND = 0.08
QUORUM_MIN_AGENTS = 3
QUORUM_FAILURE_SCORE = 0.7
WEAK_DEMOTE_FACTOR = 0.5
HARD_EVIDENCE_BOOST = 1.2


@dataclass
class ConflictReport:
    has_conflict: bool
    spread: float
    median_score: float
    high_deviants: list[str]
    low_deviants: list[str]
    degraded_agents: list[str]
    borderline: bool
    needs_arbitration: bool
    trigger_reason: str = "NONE"


@dataclass
class ArbitrationVerdict:
    triggered: bool
    trigger_reason: str
    adjusted_confidence: dict[str, float]
    excluded_agents: list[str]
    escalation: str
    rationale: str
    method: str
    adjustments: list[dict] = field(default_factory=list)

    @classmethod
    def not_triggered(cls) -> "ArbitrationVerdict":
        return cls(
            triggered=False,
            trigger_reason="NONE",
            adjusted_confidence={},
            excluded_agents=[],
            escalation="NONE",
            rationale="各 Agent 意见一致性良好，无需仲裁。",
            method="none",
        )


@dataclass
class FusionResult:
    risk_score: float
    contributions: list[dict]
    method: str = "confidence-weighted"
    quorum_failure: bool = False


def analyze_conflict(outputs: list[AgentOutput], strategy) -> ConflictReport:
    """冲突分析只对有效（非降级）Agent 计算：降级输出无有效风险意见，
    不应参与 spread/中位数/离群归因/边界带判定，否则会制造虚假冲突。"""
    active = [output for output in outputs if not output.degraded]
    scores = [output.risk_score for output in active]
    spread = max(scores) - min(scores) if scores else 0.0
    mid = median(scores) if scores else 0.0
    has_conflict = spread > strategy.conflict_threshold
    high_deviants = [o.agent_id for o in active if o.risk_score > mid + DEVIATION_RATIO * spread]
    low_deviants = [o.agent_id for o in active if o.risk_score < mid - DEVIATION_RATIO * spread]
    degraded = [o.agent_id for o in outputs if o.degraded]
    if active:
        preliminary = fuse(active, strategy.agent_weights, ArbitrationVerdict.not_triggered())
    else:
        preliminary = FusionResult(risk_score=QUORUM_FAILURE_SCORE, contributions=[], quorum_failure=True)
    borderline = strategy.review_threshold - BORDERLINE_BAND <= preliminary.risk_score < strategy.review_threshold
    needs_arbitration = has_conflict or borderline or bool(degraded)
    if has_conflict:
        reason = "CONFLICT"
    elif borderline:
        reason = "BORDERLINE"
    elif degraded:
        reason = "DEGRADED"
    else:
        reason = "NONE"
    return ConflictReport(
        has_conflict=has_conflict,
        spread=round(spread, 4),
        median_score=round(mid, 4),
        high_deviants=high_deviants,
        low_deviants=low_deviants,
        degraded_agents=degraded,
        borderline=borderline,
        needs_arbitration=needs_arbitration,
        trigger_reason=reason,
    )


def _strong_signal(output: AgentOutput) -> bool:
    return output.risk_label == "BLACKLIST_HIT"


def rule_arbitrate(outputs: list[AgentOutput], report: ConflictReport, strategy) -> ArbitrationVerdict:
    by_id = {output.agent_id: output for output in outputs}
    adjusted = {output.agent_id: output.confidence for output in outputs}
    excluded = list(report.degraded_agents)
    actions: list[dict] = []
    escalation = "NONE"
    notes: list[str] = []

    if excluded:
        notes.append(f"降级 Agent（超时/异常）已从融合中剔除：{'、'.join(excluded)}")

    active = [o for o in outputs if o.agent_id not in excluded]
    if len(active) < QUORUM_MIN_AGENTS:
        escalation = "ESCALATE_REVIEW"
        notes.append(f"有效 Agent 仅 {len(active)} 个（不足 {QUORUM_MIN_AGENTS}），保守转人工复核。")

    for agent_id in report.high_deviants + report.low_deviants:
        output = by_id.get(agent_id)
        if output is None or agent_id in excluded:
            continue
        before = adjusted[agent_id]
        if _strong_signal(output):
            adjusted[agent_id] = min(1.0, round(before * HARD_EVIDENCE_BOOST, 4))
            actions.append(
                {"agent_id": agent_id, "confidence_before": before, "confidence_after": adjusted[agent_id], "action": "UPWEIGHT"}
            )
            notes.append(f"{agent_id} 持硬证据（名单命中），提升话语权。")
        elif output.confidence < WEAK_CONFIDENCE:
            adjusted[agent_id] = round(before * WEAK_DEMOTE_FACTOR, 4)
            actions.append(
                {"agent_id": agent_id, "confidence_before": before, "confidence_after": adjusted[agent_id], "action": "DOWNWEIGHT"}
            )
            side = "高" if agent_id in report.high_deviants else "低"
            notes.append(f"{agent_id} 为{side}侧离群且置信度不足（{output.confidence:.2f}），意见降权。")

    high_side_ids = [o.agent_id for o in active if o.risk_score > report.median_score]

    # 可信风险主张：评分达到复核阈值且置信度达标，或持硬证据（名单命中）
    strong_high = [
        o.agent_id
        for o in active
        if (o.risk_score >= strategy.review_threshold and o.confidence >= WEAK_CONFIDENCE) or _strong_signal(o)
    ]
    if report.has_conflict and strong_high:
        escalation = "ESCALATE_REVIEW"
        notes.append(f"意见分歧显著，且 {'、'.join(strong_high)} 以充分置信度给出风险主张，保守升级人工复核。")
    elif report.has_conflict and high_side_ids and not strong_high:
        notes.append("高侧告警未达到可信风险主张标准（低置信或评分不足），降权后按融合分放行（降低误报）。")

    if report.borderline and escalation == "NONE":
        dissent = [
            o for o in active if o.risk_score >= strategy.review_threshold and o.confidence >= STRONG_DISSENT_CONFIDENCE
        ]
        if dissent:
            escalation = "ESCALATE_REVIEW"
            notes.append(f"融合分处于复核阈值边界，且 {'、'.join(o.agent_id for o in dissent)} 以高置信度示警，升级人工复核。")

    if not active:
        notes.append("全部 Agent 降级，按保守分处理。")
        escalation = "ESCALATE_REVIEW"

    return ArbitrationVerdict(
        triggered=True,
        trigger_reason=report.trigger_reason,
        adjusted_confidence=adjusted,
        excluded_agents=excluded,
        escalation=escalation,
        rationale="；".join(notes) or "未触发实质性调整。",
        method="rule",
        adjustments=actions,
    )


def arbitrate(payload: dict, outputs: list[AgentOutput], report: ConflictReport, strategy, llm_client=None) -> ArbitrationVerdict:
    """仲裁编排：LLM 启用时优先 LLM-as-Judge，失败/超时/未启用回退规则仲裁。

    安全基线由规则仲裁保证：降级剔除与法定人数升级不可被 LLM 降低，
    LLM 只能在基线之上做置信度精细化调整或进一步升级。
    """
    baseline = rule_arbitrate(outputs, report, strategy)
    if llm_client is None or not llm_client.enabled():
        return baseline
    agent_payloads = [
        {
            "agent_id": o.agent_id,
            "risk_score": o.risk_score,
            "risk_label": o.risk_label,
            "confidence": o.confidence,
            "evidence": o.evidence[0]["summary"] if o.evidence else "",
        }
        for o in outputs
        if not o.degraded
    ]
    try:
        result = llm_client.arbitrate_conflict(
            transaction=payload,
            agent_outputs=agent_payloads,
            conflict_analysis={
                "spread": report.spread,
                "median_score": report.median_score,
                "high_deviants": report.high_deviants,
                "low_deviants": report.low_deviants,
                "degraded_agents": report.degraded_agents,
            },
        )
    except Exception:
        return baseline
    if not isinstance(result, dict):
        return baseline
    verdict = _merge_llm_verdict(baseline, result, outputs, report)
    return verdict if verdict is not None else baseline


def _merge_llm_verdict(baseline: ArbitrationVerdict, result: dict, outputs: list[AgentOutput], report: ConflictReport) -> ArbitrationVerdict | None:
    by_id = {o.agent_id: o for o in outputs}
    adjusted = dict(baseline.adjusted_confidence)
    actions: list[dict] = []
    for agent_id, multiplier in (result.get("trust_adjustments") or {}).items():
        if agent_id not in by_id or not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
            return None
        base = adjusted.get(agent_id, by_id[agent_id].confidence)
        new_confidence = round(min(1.0, max(0.05, base * float(multiplier))), 4)
        if abs(new_confidence - base) > 1e-9:
            adjusted[agent_id] = new_confidence
            actions.append(
                {
                    "agent_id": agent_id,
                    "confidence_before": base,
                    "confidence_after": new_confidence,
                    "action": "UPWEIGHT" if new_confidence > base else "DOWNWEIGHT",
                }
            )
    escalation = result.get("escalation")
    if escalation not in {"NONE", "ESCALATE_REVIEW", "ESCALATE_BLOCK"}:
        return None
    rationale = result.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    rationale = rationale.strip()
    if baseline.escalation == "ESCALATE_BLOCK":
        escalation = "ESCALATE_BLOCK"
    elif baseline.escalation == "ESCALATE_REVIEW" and escalation == "NONE":
        escalation = "ESCALATE_REVIEW"
    if baseline.escalation == "ESCALATE_REVIEW" and escalation == "ESCALATE_REVIEW" and "法定人数" in baseline.rationale and "法定人数" not in rationale:
        rationale = f"{rationale}（含法定人数不足的保守升级）"
    return ArbitrationVerdict(
        triggered=True,
        trigger_reason=report.trigger_reason,
        adjusted_confidence=adjusted,
        excluded_agents=baseline.excluded_agents,
        escalation=escalation,
        rationale=rationale,
        method="llm",
        adjustments=actions,
    )


def fuse(outputs: list[AgentOutput], weights: dict, verdict: ArbitrationVerdict) -> FusionResult:
    contributions: list[dict] = []
    active = [o for o in outputs if o.agent_id not in verdict.excluded_agents]
    if not active:
        return FusionResult(
            risk_score=QUORUM_FAILURE_SCORE,
            contributions=contributions,
            quorum_failure=True,
        )
    total_effective = 0.0
    weighted_sum = 0.0
    for output in active:
        strategy_weight = float(weights.get(output.agent_id, 0.2))
        confidence = verdict.adjusted_confidence.get(output.agent_id, output.confidence)
        effective = strategy_weight * confidence
        weighted_sum += output.risk_score * effective
        total_effective += effective
        contributions.append(
            {
                "agent_id": output.agent_id,
                "strategy_weight": round(strategy_weight, 4),
                "confidence": round(confidence, 4),
                "effective_weight": round(effective, 6),
                "score": output.risk_score,
                "contribution": round(output.risk_score * effective, 6),
            }
        )
    risk_score = weighted_sum / total_effective if total_effective else QUORUM_FAILURE_SCORE
    return FusionResult(risk_score=round(risk_score, 4), contributions=contributions)


def decide(outputs: list[AgentOutput], fusion: FusionResult, verdict: ArbitrationVerdict, strategy) -> str:
    if fusion.quorum_failure:
        return "REVIEW"
    if any(_strong_signal(output) for output in outputs if not output.degraded):
        return "BLOCK"
    if fusion.risk_score >= strategy.block_threshold or verdict.escalation == "ESCALATE_BLOCK":
        return "BLOCK"
    if fusion.risk_score >= strategy.review_threshold or verdict.escalation == "ESCALATE_REVIEW":
        return "REVIEW"
    return "PASS"


def build_stage1(outputs: list[AgentOutput]) -> dict:
    return {
        "round_id": 1,
        "name": "独立评估",
        "agents": [
            {
                "agent_id": output.agent_id,
                "agent_type": output.agent_type,
                "risk_score": output.risk_score,
                "risk_label": output.risk_label,
                "confidence": output.confidence,
                "exec_time_ms": output.exec_time_ms,
                "evidence_top": output.evidence[0]["summary"] if output.evidence else "",
                "degraded": output.degraded,
            }
            for output in outputs
        ],
    }


def build_stage2(report: ConflictReport, verdict: ArbitrationVerdict) -> dict:
    return {
        "round_id": 2,
        "name": "冲突仲裁",
        "triggered": verdict.triggered,
        "reason": verdict.trigger_reason,
        "method": verdict.method,
        "conflict": {
            "spread": report.spread,
            "median_score": report.median_score,
            "high_deviants": report.high_deviants,
            "low_deviants": report.low_deviants,
            "degraded_agents": report.degraded_agents,
        },
        "rationale": verdict.rationale,
        "escalation": verdict.escalation,
        "adjustments": verdict.adjustments,
    }


def build_fusion_stage(fusion: FusionResult, verdict: ArbitrationVerdict) -> dict:
    return {
        "method": fusion.method,
        "contributions": fusion.contributions,
        "final_score": fusion.risk_score,
        "excluded_agents": verdict.excluded_agents,
        "quorum_failure": fusion.quorum_failure,
    }
