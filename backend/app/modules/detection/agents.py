import hashlib
from dataclasses import dataclass, field
from time import perf_counter

from app.core.llm import LLMClient


@dataclass
class AgentOutput:
    agent_id: str
    agent_type: str
    risk_score: float
    risk_label: str
    evidence: list[dict] = field(default_factory=list)
    exec_time_ms: int = 0
    degraded: bool = False
    confidence: float = 0.8
    round_id: int = 1


def clamp_confidence(value: float) -> float:
    return round(max(0.05, min(1.0, value)), 4)


def stable_noise(transaction: dict, salt: str, span: float = 0.035) -> float:
    seed = "|".join(
        str(transaction.get(key, ""))
        for key in ["transaction_id", "user_id", "amount", "channel", "device_id", "merchant_id", "location", "counterparty_type"]
    )
    digest = hashlib.sha256(f"{salt}|{seed}".encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    return (ratio - 0.5) * 2 * span


def clamp_score(value: float) -> float:
    return round(max(0.01, min(0.99, value)), 4)


def factor_score(value: str, mapping: dict[str, float], default: float = 0.0) -> float:
    return mapping.get(value, default)


class DetectionAgent:
    agent_id = "base"
    agent_type = "BASE"
    timeout_seconds: float = 0.3

    def analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        started = perf_counter()
        output = self._analyze(transaction, feature_bundle)
        output.risk_score = clamp_score(output.risk_score + stable_noise(transaction, self.agent_id))
        output.evidence.append({"summary": "上下文稳定扰动已纳入评分", "score": output.risk_score})
        output.exec_time_ms = max(1, int((perf_counter() - started) * 1000))
        return output

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        raise NotImplementedError


class ListMatchAgent(DetectionAgent):
    agent_id = "list-match"
    agent_type = "LIST"

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        hit = feature_bundle.get("blacklist_hit")
        target_type = transaction.get("counterparty_type", "")
        checked = int(feature_bundle.get("list_fields_checked", 0))
        score = 0.93 if hit else 0.08
        score += factor_score(target_type, {"对私转账（陌生人）": 0.08, "个人卖家": 0.03, "网络电商": 0.01})
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            score,
            "BLACKLIST_HIT" if hit else "NO_LIST_HIT",
            [{"summary": "命中高危名单" if hit else f"名单未命中，交易对象={target_type or '未提供'}", "score": clamp_score(score)}],
            confidence=clamp_confidence(0.55 + 0.1 * checked),
        )


class TransactionAnalysisAgent(DetectionAgent):
    agent_id = "transaction-analysis"
    agent_type = "TRANSACTION"

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        amount = float(transaction.get("amount") or 0)
        channel = transaction.get("channel", "")
        target_type = transaction.get("counterparty_type", "")
        if amount < 500:
            amount_score = 0.08 + amount / 10_000
        elif amount < 20_000:
            amount_score = 0.16 + amount / 160_000
        elif amount < 300_000:
            amount_score = 0.32 + amount / 1_000_000
        else:
            amount_score = 0.52 + min(amount, 1_500_000) / 3_000_000
        score = amount_score
        score += factor_score(channel, {"线下当面交易": 0.04, "网络平台": 0.02, "私人转账": 0.09, "其他渠道": 0.07})
        score += factor_score(target_type, {"对私转账（陌生人）": 0.10, "个人卖家": 0.05, "对公转账": -0.03, "网络电商": -0.04})
        label = "LARGE_AMOUNT" if score >= 0.6 else "NORMAL_AMOUNT"
        confidence = 0.9 if target_type else 0.65
        if not channel:
            confidence -= 0.05
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            score,
            label,
            [{"summary": f"金额={amount:.2f}，渠道={channel}，交易对象={target_type}", "score": clamp_score(score)}],
            confidence=clamp_confidence(confidence),
        )


class BehaviorModelingAgent(DetectionAgent):
    agent_id = "behavior-modeling"
    agent_type = "BEHAVIOR"

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        location = transaction.get("location", "")
        home = feature_bundle.get("last_login_location")
        unusual_location = bool(location and location != home)
        night = bool(transaction.get("night_operation"))
        channel = transaction.get("channel", "")
        score = 0.18
        if unusual_location:
            score += 0.22
        if night:
            score += 0.18
        score += factor_score(channel, {"私人转账": 0.07, "其他渠道": 0.05, "线下当面交易": -0.02})
        has_profile = bool(feature_bundle.get("has_profile"))
        if has_profile and location:
            confidence = 0.85
        elif has_profile:
            confidence = 0.55
        elif location:
            confidence = 0.5
        else:
            confidence = 0.45
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            score,
            "BEHAVIOR_ANOMALY" if score >= 0.55 else "BEHAVIOR_NORMAL",
            [{"summary": f"常用地={home or '未知'}，交易地={location or '未知'}，夜间={night}", "score": clamp_score(score)}],
            confidence=clamp_confidence(confidence),
        )


class DeviceFingerprintAgent(DetectionAgent):
    agent_id = "device-fingerprint"
    agent_type = "DEVICE"

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        device_id = transaction.get("device_id", "")
        shared_count = feature_bundle.get("shared_device_count", 0)
        risky = device_id.endswith("X") or shared_count >= 3
        score = 0.16 + min(shared_count, 5) * 0.045
        if risky:
            score += 0.34
        if "WINDOWS" in device_id.upper():
            score += 0.03
        if "IPHONE" in device_id.upper():
            score -= 0.02
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            score,
            "DEVICE_RISK" if risky else "DEVICE_NORMAL",
            [{"summary": f"设备={device_id or '未知'}，复用计数={shared_count}", "score": clamp_score(score)}],
            confidence=clamp_confidence(0.85 if device_id else 0.4),
        )


class GraphTraceAgent(DetectionAgent):
    agent_id = "graph-trace"
    agent_type = "GRAPH"

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        hops = int(feature_bundle.get("risk_graph_hops", 0))
        target_type = transaction.get("counterparty_type", "")
        merchant_id = transaction.get("merchant_id", "")
        score = 0.10 + hops * 0.13
        score += factor_score(target_type, {"对私转账（陌生人）": 0.12, "个人卖家": 0.05, "对私转账（熟人）": -0.04, "对公转账": -0.03})
        if merchant_id and target_type:
            confidence = 0.7
        elif merchant_id or target_type:
            confidence = 0.55
        else:
            confidence = 0.45
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            score,
            "GRAPH_CLUSTER" if score >= 0.58 else "GRAPH_CLEAR",
            [{"summary": f"关联风险节点={hops}，交易对象={target_type or '未提供'}", "score": clamp_score(score)}],
            confidence=clamp_confidence(confidence),
        )


class SemanticAnalysisAgent(DetectionAgent):
    """LLM 驱动的语义分析 Agent：解析申诉理由、备注、聊天记录等非结构化线索。

    与规则 Agent 同构输出（risk_score / risk_label / evidence / confidence），
    参与冲突分析与置信度加权融合；LLM 未启用、无线索、调用失败或输出不可解析时，
    返回降级输出（degraded=True，融合阶段剔除，不注入保守分）。
    """
    agent_id = "semantic-analysis"
    agent_type = "SEMANTIC"
    timeout_seconds: float = 3.5

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def _analyze(self, transaction: dict, feature_bundle: dict) -> AgentOutput:
        clues = list(feature_bundle.get("semantic_clues") or [])
        if not clues or not self.llm_client.enabled():
            return AgentOutput(
                self.agent_id,
                self.agent_type,
                0.8,
                "LLM_UNAVAILABLE",
                [{"summary": "无语义线索或 LLM 未启用，降级剔除", "score": 0.8}],
                degraded=True,
                confidence=0.2,
            )
        result = self.llm_client.analyze_semantic_risk(transaction=transaction, clues=clues)
        if result is None:
            return AgentOutput(
                self.agent_id,
                self.agent_type,
                0.8,
                "SEMANTIC_ANALYSIS_FAILED",
                [{"summary": "语义分析失败或输出不可解析，降级剔除", "score": 0.8}],
                degraded=True,
                confidence=0.2,
            )
        return AgentOutput(
            self.agent_id,
            self.agent_type,
            result["risk_score"],
            result["risk_label"],
            result["evidence"],
            confidence=clamp_confidence(result["confidence"]),
        )


AGENTS: list[DetectionAgent] = [
    ListMatchAgent(),
    TransactionAnalysisAgent(),
    BehaviorModelingAgent(),
    DeviceFingerprintAgent(),
    GraphTraceAgent(),
    SemanticAnalysisAgent(),
]
