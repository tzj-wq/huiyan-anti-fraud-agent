from types import SimpleNamespace

from app.modules.detection.agents import (
    AGENTS,
    AgentOutput,
    BehaviorModelingAgent,
    DeviceFingerprintAgent,
    GraphTraceAgent,
    ListMatchAgent,
    TransactionAnalysisAgent,
    clamp_confidence,
)
from app.modules.detection.collaboration import (
    ArbitrationVerdict,
    analyze_conflict,
    arbitrate,
    build_fusion_stage,
    build_stage1,
    build_stage2,
    decide,
    fuse,
    rule_arbitrate,
)
from app.core.llm import LLMClient


def make_strategy(**overrides):
    base = {
        "agent_weights": {
            "list-match": 0.28,
            "transaction-analysis": 0.22,
            "behavior-modeling": 0.18,
            "device-fingerprint": 0.12,
            "graph-trace": 0.20,
        },
        "conflict_threshold": 0.4,
        "review_threshold": 0.6,
        "block_threshold": 0.85,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def output(agent_id, score, confidence=0.8, label="NORMAL", degraded=False):
    return AgentOutput(
        agent_id=agent_id,
        agent_type="TEST",
        risk_score=score,
        risk_label=label,
        evidence=[{"summary": "test", "score": score}],
        exec_time_ms=1,
        degraded=degraded,
        confidence=confidence,
    )


# ---------- 置信度：特征覆盖度规则 ----------


def test_list_match_confidence_grows_with_checked_fields():
    agent = ListMatchAgent()
    low = agent._analyze({"counterparty_type": ""}, {"blacklist_hit": False, "list_fields_checked": 1})
    high = agent._analyze({"counterparty_type": ""}, {"blacklist_hit": False, "list_fields_checked": 4})
    assert low.confidence < high.confidence
    assert high.confidence == 0.95


def test_transaction_analysis_confidence_drops_without_counterparty():
    agent = TransactionAnalysisAgent()
    full = agent._analyze({"amount": 100, "channel": "APP", "counterparty_type": "网络电商"}, {})
    partial = agent._analyze({"amount": 100, "channel": "APP"}, {})
    assert full.confidence == 0.9
    assert partial.confidence == 0.65


def test_behavior_confidence_low_without_profile():
    agent = BehaviorModelingAgent()
    no_profile = agent._analyze(
        {"location": "北京", "night_operation": True, "channel": "私人转账"},
        {"last_login_location": "", "has_profile": False},
    )
    with_profile = agent._analyze(
        {"location": "哈尔滨", "night_operation": True, "channel": "私人转账"},
        {"last_login_location": "深圳", "has_profile": True},
    )
    assert no_profile.confidence == 0.5
    assert with_profile.confidence == 0.85
    assert no_profile.risk_score > with_profile.risk_score - 0.4  # 无画像时异地判断激进，仍应给出高分告警


def test_device_and_graph_confidence_rules():
    device = DeviceFingerprintAgent()
    assert device._analyze({"device_id": "DEV-1"}, {"shared_device_count": 1}).confidence == 0.85
    assert device._analyze({"device_id": ""}, {"shared_device_count": 1}).confidence == 0.4
    graph = GraphTraceAgent()
    assert graph._analyze({"merchant_id": "M", "counterparty_type": "网络电商"}, {"risk_graph_hops": 1}).confidence == 0.7
    assert graph._analyze({"merchant_id": "", "counterparty_type": ""}, {"risk_graph_hops": 1}).confidence == 0.45


def test_all_registered_agents_report_confidence():
    payload = {
        "user_id": "U1",
        "amount": 5000,
        "channel": "APP",
        "device_id": "DEV-1",
        "merchant_id": "MCH-1",
        "counterparty_type": "网络电商",
        "location": "上海",
    }
    features = {
        "blacklist_hit": False,
        "list_fields_checked": 4,
        "has_profile": True,
        "last_login_location": "上海",
        "shared_device_count": 1,
        "risk_graph_hops": 1,
    }
    for agent in AGENTS:
        result = agent.analyze(payload, features)
        assert 0.05 <= result.confidence <= 1.0
        assert len(result.evidence) >= 1


# ---------- 冲突分析 ----------


def test_conflict_analysis_identifies_deviants():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.08, 0.95),
        output("transaction-analysis", 0.69, 0.65),
        output("behavior-modeling", 0.58, 0.85),
        output("device-fingerprint", 0.20, 0.85),
        output("graph-trace", 0.23, 0.55),
    ]
    report = analyze_conflict(outputs, strategy)
    assert report.has_conflict
    assert report.spread > 0.4
    assert "transaction-analysis" in report.high_deviants
    assert report.needs_arbitration
    assert report.trigger_reason == "CONFLICT"


def test_consistent_scores_need_no_arbitration():
    strategy = make_strategy()
    outputs = [output("a", 0.20), output("b", 0.22), output("c", 0.25), output("d", 0.28), output("e", 0.30)]
    report = analyze_conflict(outputs, strategy)
    assert not report.has_conflict
    assert not report.needs_arbitration


# ---------- 规则仲裁 ----------


def test_weak_high_alarm_downweighted_without_escalation():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.08, 0.95),
        output("transaction-analysis", 0.27, 0.65),
        output("behavior-modeling", 0.65, 0.5),
        output("device-fingerprint", 0.21, 0.85),
        output("graph-trace", 0.23, 0.55),
    ]
    report = analyze_conflict(outputs, strategy)
    assert report.has_conflict
    assert "behavior-modeling" in report.high_deviants
    verdict = rule_arbitrate(outputs, report, strategy)
    assert verdict.method == "rule"
    assert verdict.adjusted_confidence["behavior-modeling"] < outputs[2].confidence
    assert verdict.escalation == "NONE"
    fusion = fuse(outputs, strategy.agent_weights, verdict)
    assert fusion.risk_score < 0.6
    assert decide(outputs, fusion, verdict, strategy) == "PASS"


def test_strong_high_alarm_escalates_to_review():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.08, 0.95),
        output("transaction-analysis", 0.82, 0.65),
        output("behavior-modeling", 0.18, 0.85),
        output("device-fingerprint", 0.21, 0.85),
        output("graph-trace", 0.23, 0.55),
    ]
    report = analyze_conflict(outputs, strategy)
    verdict = rule_arbitrate(outputs, report, strategy)
    assert verdict.escalation == "ESCALATE_REVIEW"
    fusion = fuse(outputs, strategy.agent_weights, verdict)
    assert decide(outputs, fusion, verdict, strategy) == "REVIEW"


def test_blacklist_hit_is_hard_evidence():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.93, 0.95, label="BLACKLIST_HIT"),
        output("transaction-analysis", 0.30, 0.9),
        output("behavior-modeling", 0.20, 0.85),
        output("device-fingerprint", 0.20, 0.85),
        output("graph-trace", 0.20, 0.7),
    ]
    report = analyze_conflict(outputs, strategy)
    verdict = rule_arbitrate(outputs, report, strategy)
    assert verdict.adjusted_confidence["list-match"] > outputs[0].confidence
    fusion = fuse(outputs, strategy.agent_weights, verdict)
    assert decide(outputs, fusion, verdict, strategy) == "BLOCK"


def test_degraded_agents_excluded_and_quorum_escalates():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.08, 0.2, degraded=True),
        output("transaction-analysis", 0.30, 0.2, degraded=True),
        output("behavior-modeling", 0.20, 0.2, degraded=True),
        output("device-fingerprint", 0.21, 0.85),
        output("graph-trace", 0.23, 0.7),
    ]
    report = analyze_conflict(outputs, strategy)
    assert report.degraded_agents == ["list-match", "transaction-analysis", "behavior-modeling"]
    verdict = rule_arbitrate(outputs, report, strategy)
    assert set(verdict.excluded_agents) == set(report.degraded_agents)
    assert verdict.escalation == "ESCALATE_REVIEW"  # 剩余 2 < 3，法定人数不足
    fusion = fuse(outputs, strategy.agent_weights, verdict)
    assert decide(outputs, fusion, verdict, strategy) == "REVIEW"
    assert all(c["agent_id"] not in verdict.excluded_agents for c in fusion.contributions)


def test_all_degraded_falls_back_to_conservative_review():
    strategy = make_strategy()
    outputs = [output(a, 0.8, 0.2, degraded=True) for a in ["a", "b", "c", "d", "e"]]
    verdict = rule_arbitrate(outputs, analyze_conflict(outputs, strategy), strategy)
    fusion = fuse(outputs, strategy.agent_weights, verdict)
    assert fusion.quorum_failure
    assert fusion.risk_score == 0.7
    assert decide(outputs, fusion, verdict, strategy) == "REVIEW"


def test_borderline_with_strong_dissent_escalates():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.55, 0.95),
        output("transaction-analysis", 0.60, 0.9),
        output("behavior-modeling", 0.58, 0.85),
        output("device-fingerprint", 0.50, 0.85),
        output("graph-trace", 0.45, 0.7),
    ]
    report = analyze_conflict(outputs, strategy)
    assert not report.has_conflict
    assert report.borderline
    assert report.trigger_reason == "BORDERLINE"
    verdict = rule_arbitrate(outputs, report, strategy)
    assert verdict.escalation == "ESCALATE_REVIEW"
    assert "边界" in verdict.rationale


# ---------- 融合数学 ----------


def test_fusion_is_confidence_weighted():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.10, 0.5),
        output("transaction-analysis", 0.90, 0.5),
        output("behavior-modeling", 0.50, 1.0),
        output("device-fingerprint", 0.50, 1.0),
        output("graph-trace", 0.50, 1.0),
    ]
    fusion = fuse(outputs, strategy.agent_weights, ArbitrationVerdict.not_triggered())
    # 高置信的行为/设备/图三个 0.5 分主导，融合分应更接近 0.5 而非简单平均 0.5
    assert 0.35 < fusion.risk_score < 0.65
    assert len(fusion.contributions) == 5
    total_effective = sum(c["effective_weight"] for c in fusion.contributions)
    assert abs(sum(c["contribution"] for c in fusion.contributions) / total_effective - fusion.risk_score) < 1e-6


def test_stage_builders_shape():
    strategy = make_strategy()
    outputs = [
        output("list-match", 0.08, 0.95),
        output("transaction-analysis", 0.82, 0.65),
        output("behavior-modeling", 0.18, 0.85),
        output("device-fingerprint", 0.21, 0.85),
        output("graph-trace", 0.23, 0.55),
    ]
    stage1 = build_stage1(outputs)
    assert stage1["round_id"] == 1
    assert len(stage1["agents"]) == 5
    assert all("confidence" in agent and "evidence_top" in agent for agent in stage1["agents"])

    report = analyze_conflict(outputs, strategy)
    verdict = rule_arbitrate(outputs, report, strategy)
    stage2 = build_stage2(report, verdict)
    assert stage2["round_id"] == 2
    assert stage2["method"] == "rule"
    assert stage2["rationale"]

    fusion = fuse(outputs, strategy.agent_weights, verdict)
    fusion_stage = build_fusion_stage(fusion, verdict)
    assert fusion_stage["final_score"] == fusion.risk_score
    assert len(fusion_stage["contributions"]) == 5


# ---------- LLM-as-Judge 仲裁 ----------


class FakeLLM:
    def __init__(self, result=None, enabled=True, raise_exc=False):
        self.result = result
        self._enabled = enabled
        self.raise_exc = raise_exc
        self.calls = 0

    def enabled(self):
        return self._enabled

    def arbitrate_conflict(self, **kwargs):
        self.calls += 1
        assert "transaction" in kwargs and "agent_outputs" in kwargs and "conflict_analysis" in kwargs
        if self.raise_exc:
            raise RuntimeError("llm down")
        return self.result


def conflict_outputs():
    return [
        output("list-match", 0.08, 0.95),
        output("transaction-analysis", 0.82, 0.65),
        output("behavior-modeling", 0.18, 0.85),
        output("device-fingerprint", 0.21, 0.85),
        output("graph-trace", 0.23, 0.55),
    ]


def test_llm_arbitration_applies_adjustments():
    strategy = make_strategy()
    outputs = conflict_outputs()
    report = analyze_conflict(outputs, strategy)
    fake = FakeLLM(
        result={
            "trust_adjustments": {"transaction-analysis": 0.5, "graph-trace": 1.3},
            "escalation": "NONE",
            "rationale": "交易分析证据不足，降权处理。",
        }
    )
    verdict = arbitrate({"user_id": "U1"}, outputs, report, strategy, llm_client=fake)
    assert fake.calls == 1
    assert verdict.method == "llm"
    assert verdict.adjusted_confidence["transaction-analysis"] < 0.65
    assert verdict.adjusted_confidence["graph-trace"] > 0.55
    assert verdict.rationale.startswith("交易分析")
    assert any(item["action"] == "DOWNWEIGHT" and item["agent_id"] == "transaction-analysis" for item in verdict.adjustments)


def test_llm_cannot_lower_quorum_escalation():
    strategy = make_strategy()
    outputs = [output(a, 0.8, 0.2, degraded=True) for a in ["a", "b", "c", "d", "e"]]
    report = analyze_conflict(outputs, strategy)
    fake = FakeLLM(result={"trust_adjustments": {}, "escalation": "NONE", "rationale": "LLM 认为无风险。"})
    verdict = arbitrate({}, outputs, report, strategy, llm_client=fake)
    # 全部降级 → 规则基线强制保守复核，LLM 无法降级该安全结论
    assert verdict.escalation == "ESCALATE_REVIEW"
    assert verdict.method == "llm"


def test_llm_invalid_payload_falls_back_to_rule():
    strategy = make_strategy()
    outputs = conflict_outputs()
    report = analyze_conflict(outputs, strategy)
    for bad_result in [
        None,
        "not a dict",
        {"trust_adjustments": {"unknown-agent": 0.5}, "escalation": "NONE", "rationale": "x"},
        {"trust_adjustments": {"transaction-analysis": "fast"}, "escalation": "NONE", "rationale": "x"},
        {"trust_adjustments": {}, "escalation": "ESCALATE_YOLO", "rationale": "x"},
        {"trust_adjustments": {}, "escalation": "NONE"},
    ]:
        fake = FakeLLM(result=bad_result)
        verdict = arbitrate({}, outputs, report, strategy, llm_client=fake)
        assert verdict.method == "rule", f"should fall back for {bad_result!r}"


def test_llm_exception_or_disabled_falls_back():
    strategy = make_strategy()
    outputs = conflict_outputs()
    report = analyze_conflict(outputs, strategy)
    verdict = arbitrate({}, outputs, report, strategy, llm_client=FakeLLM(raise_exc=True))
    assert verdict.method == "rule"
    verdict = arbitrate({}, outputs, report, strategy, llm_client=FakeLLM(enabled=False))
    assert verdict.method == "rule"
    verdict = arbitrate({}, outputs, report, strategy, llm_client=None)
    assert verdict.method == "rule"


def test_llm_parse_arbitration_content():
    parse = LLMClient._parse_arbitration
    good = '{"trust_adjustments": {"a": 1.2}, "escalation": "ESCALATE_REVIEW", "rationale": "高风险"}'
    assert parse(f"前置说明 {good} 后置说明")["escalation"] == "ESCALATE_REVIEW"
    assert parse("完全不是 JSON") is None
    assert parse('{"escalation": "BAD", "rationale": "x"}') is None
    assert parse('{"trust_adjustments": {}, "escalation": "NONE"}') is None
