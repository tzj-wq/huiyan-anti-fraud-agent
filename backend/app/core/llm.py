from __future__ import annotations

from dataclasses import dataclass, field
import json

import httpx

from app.core.config import get_settings

ARBITRATION_TIMEOUT_SECONDS = 3.0
SEMANTIC_TIMEOUT_SECONDS = 3.0


@dataclass
class LLMDecisionInsight:
    enabled: bool
    provider: str
    model: str
    summary: str
    recommendation: str
    fallback: bool = False
    evidence: list[str] = field(default_factory=list)
    audit_note: str = ""


class LLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def enabled(self) -> bool:
        return bool(self.settings.llm_enabled and self.settings.llm_api_key)

    def explain_decision(self, *, transaction: dict, agent_outputs: list[dict], decision: str, risk_score: float) -> LLMDecisionInsight:
        """LLM 生成结构化决策解释：摘要 / 证据 / 处置建议 / 审计说明。

        LLM 输出严格 JSON；调用失败、超时或输出不可解析时回退到规则模板（fallback=True）。
        """
        fallback = self._fallback(transaction=transaction, agent_outputs=agent_outputs, decision=decision, risk_score=risk_score)
        if not self.enabled():
            return fallback
        try:
            content = self._call_openai_compatible(transaction, agent_outputs, decision, risk_score)
        except Exception:
            return LLMDecisionInsight(
                enabled=False,
                provider=self.settings.llm_provider,
                model=self.settings.llm_model,
                summary=fallback.summary,
                recommendation=fallback.recommendation,
                fallback=True,
            )
        parsed = self._parse_explanation(content)
        if parsed is None:
            return LLMDecisionInsight(
                enabled=False,
                provider=self.settings.llm_provider,
                model=self.settings.llm_model,
                summary=fallback.summary,
                recommendation=fallback.recommendation,
                fallback=True,
            )
        return LLMDecisionInsight(
            enabled=True,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
            summary=parsed["summary"],
            recommendation=parsed["recommendation"],
            evidence=parsed["evidence"],
            audit_note=parsed["audit_note"],
        )

    def assess_security(self, snapshot: dict) -> dict:
        fallback = self._security_fallback(snapshot)
        if not self.enabled():
            return fallback
        prompt = (
            "你是个人账户安全体检助手。请根据登录设备、MFA开关、隐私授权和最近操作日志，"
            "输出三项：评分(0-100)、主要问题、改进建议。要求简洁、可执行。\n\n"
            f"安全快照: {snapshot}"
        )
        try:
            content = self._call_prompt(system="你负责生成个人账户安全体检结论。", user=prompt)
        except Exception:
            return {**fallback, "fallback": True}
        return {
            "score": fallback["score"],
            "level": fallback["level"],
            "summary": content.strip(),
            "recommendations": fallback["recommendations"],
            "llm": self.status(),
            "fallback": False,
        }

    def arbitrate_conflict(self, *, transaction: dict, agent_outputs: list[dict], conflict_analysis: dict) -> dict | None:
        """LLM-as-Judge：对冲突交易给出结构化仲裁意见。

        返回 {"trust_adjustments": {agent_id: multiplier}, "escalation": str, "rationale": str}；
        未启用、调用失败、超时或输出不可解析时返回 None（调用方回退规则仲裁）。
        """
        if not self.enabled():
            return None
        prompt = (
            "你是多 Agent 反欺诈系统的冲突仲裁裁判。多个检测 Agent 对同一笔交易给出了分歧显著的风险评分，"
            "请基于各 Agent 的证据与置信度做出裁决。\n"
            "规则：已降级的 Agent 已被排除，不要为其调整；高置信且证据充分的告警应维持或提升；"
            "低置信的离群意见应降权；拿不准时宁可保守升级人工复核（ESCALATE_REVIEW）。\n\n"
            f"交易: {transaction}\n"
            f"Agent 评估: {agent_outputs}\n"
            f"冲突分析: {conflict_analysis}\n\n"
            "只输出严格 JSON，不要输出其他文字，格式：\n"
            '{"trust_adjustments": {"<agent_id>": <0.1~2.0 的置信度乘数>}, '
            '"escalation": "NONE 或 ESCALATE_REVIEW 或 ESCALATE_BLOCK", '
            '"rationale": "<60 字内中文仲裁理由>"}'
        )
        try:
            content = self._call_prompt(
                system="你负责多 Agent 反欺诈系统的冲突仲裁，输出必须是可以直接解析的 JSON。",
                user=prompt,
                timeout=ARBITRATION_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        return self._parse_arbitration(content)

    @staticmethod
    def _parse_arbitration(content: str) -> dict | None:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(content[start : end + 1])
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        adjustments = data.get("trust_adjustments")
        if adjustments is not None and not isinstance(adjustments, dict):
            return None
        escalation = data.get("escalation")
        if escalation not in {"NONE", "ESCALATE_REVIEW", "ESCALATE_BLOCK"}:
            return None
        rationale = data.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            return None
        return {
            "trust_adjustments": {key: value for key, value in (adjustments or {}).items()},
            "escalation": escalation,
            "rationale": rationale.strip(),
        }

    def analyze_semantic_risk(self, *, transaction: dict, clues: list[str], timeout: float | None = None) -> dict | None:
        """LLM 语义风险分析：解析非结构化线索（申诉理由/备注/聊天记录等）。

        返回 {"risk_score", "risk_label", "evidence": [{"summary","score"}], "confidence"}；
        未启用、调用失败、超时或输出不可解析时返回 None（调用方将 Agent 标记为降级并剔除）。
        """
        if not self.enabled() or not clues:
            return None
        prompt = (
            "你是反欺诈系统的语义风险分析 Agent。给定一笔交易和用户提供的非结构化线索"
            "（申诉理由、备注、聊天记录片段等），判断这些线索能否佐证交易真实性，"
            "或是否暴露出欺诈风险信号。\n"
            "判断规则：\n"
            "1. 线索能明确佐证真实交易（如提供有效凭证、交易背景自洽）→ 给低分（0.1~0.3）；\n"
            "2. 出现矛盾表述、规避话术、材料缺失、催促放行等风险信号 → 给高分（0.6~0.9）；\n"
            "3. 信息不足或线索含糊 → 给中性偏高（0.5~0.6），同时降低置信度（0.4~0.6）；\n"
            "4. 禁止编造线索中不存在的证据。\n\n"
            f"交易: {transaction}\n"
            f"非结构化线索: {clues}\n\n"
            "只输出严格 JSON，不要输出其他文字或代码块标记，格式：\n"
            '{"risk_score": 0.0~1.0, "risk_label": "SEMANTIC_LOW_RISK 或 SEMANTIC_MEDIUM_RISK 或 SEMANTIC_HIGH_RISK", '
            '"evidence": [{"summary": "≤30字中文证据", "score": 0.0~1.0}], "confidence": 0.0~1.0}'
        )
        try:
            content = self._call_prompt(
                system="你是反欺诈系统的语义风险分析引擎，输出必须是可以直接解析的严格 JSON。",
                user=prompt,
                timeout=timeout or SEMANTIC_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        return self._parse_semantic_risk(content)

    @staticmethod
    def _parse_semantic_risk(content: str) -> dict | None:
        """解析语义风险分析输出，校验 risk_score / risk_label / evidence / confidence 合法性。"""
        text = content.strip()
        if text.startswith("```"):
            if text.count("```") >= 2:
                text = text.split("```", 2)[1]
            else:
                text = text[3:]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            risk_score = float(data.get("risk_score"))
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            return None
        if not (0.0 <= risk_score <= 1.0 and 0.0 <= confidence <= 1.0):
            return None
        risk_label = data.get("risk_label")
        if not isinstance(risk_label, str) or not risk_label.strip():
            return None
        evidence = data.get("evidence")
        if not isinstance(evidence, list):
            return None
        normalized_evidence: list[dict] = []
        for item in evidence:
            if not isinstance(item, dict) or not isinstance(item.get("summary"), str) or not item["summary"].strip():
                return None
            try:
                item_score = float(item.get("score"))
            except (TypeError, ValueError):
                return None
            if not (0.0 <= item_score <= 1.0):
                return None
            normalized_evidence.append({"summary": item["summary"].strip(), "score": round(item_score, 4)})
        return {
            "risk_score": round(risk_score, 4),
            "risk_label": risk_label.strip(),
            "evidence": normalized_evidence,
            "confidence": round(confidence, 4),
        }

    REVIEW_ADVICE_TIMEOUT_SECONDS = 8.0

    def generate_review_advice(self, *, case_evidence: dict, candidates: list[dict]) -> dict | None:
        """LLM 生成人工审核建议（RAG 增强：结合证据链与相似历史案例）。

        返回 {"recommendation", "confidence", "rationale", "cited_cases"}；
        未启用、调用失败、超时或输出不可解析时返回 None（调用方回退规则模板）。
        """
        if not self.enabled():
            return None
        prompt = (
            "你是反欺诈系统的人工审核助手。给定案件的完整证据链和检索到的相似历史案例（含人工复核结论），"
            "给出审核建议。\n"
            "推荐动作枚举：REVIEW_CONFIRM（维持风险结论，继续拦截或跟进）；"
            "RELEASE（风险证据不足，或相似历史案例多为误报，建议放行）；"
            "ESCALATE（证据链存在明显异常、申诉与证据矛盾，或相似案例中该风险被确认，升级深度调查）。\n"
            "规则：引用历史案例必须来自给定的候选列表，不得编造；拿不准时优先 ESCALATE。\n\n"
            f"案件证据链: {case_evidence}\n"
            f"相似历史案例: {candidates}\n\n"
            "只输出严格 JSON，不要输出其他文字，格式：\n"
            '{"recommendation": "REVIEW_CONFIRM 或 RELEASE 或 ESCALATE", "confidence": 0.0~1.0, '
            '"rationale": "≤80字中文理由", "cited_cases": ["CASE-xxx"]}'
        )
        try:
            content = self._call_prompt(
                system="你是反欺诈人工审核决策引擎，输出必须是可以直接解析的严格 JSON。",
                user=prompt,
                timeout=self.REVIEW_ADVICE_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        return self._parse_review_advice(content)

    @staticmethod
    def _parse_review_advice(content: str) -> dict | None:
        """解析审核建议输出，校验 recommendation / confidence / rationale / cited_cases。"""
        text = content.strip()
        if text.startswith("```"):
            if text.count("```") >= 2:
                text = text.split("```", 2)[1]
            else:
                text = text[3:]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        recommendation = data.get("recommendation")
        if recommendation not in {"REVIEW_CONFIRM", "RELEASE", "ESCALATE"}:
            return None
        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            return None
        if not (0.0 <= confidence <= 1.0):
            return None
        rationale = data.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            return None
        cited = data.get("cited_cases")
        if cited is not None and (not isinstance(cited, list) or not all(isinstance(item, str) for item in cited)):
            return None
        return {
            "recommendation": recommendation,
            "confidence": round(confidence, 4),
            "rationale": rationale.strip(),
            "cited_cases": [item.strip() for item in (cited or [])],
        }

    def status(self) -> dict:
        reason = "enabled"
        if not self.settings.llm_enabled:
            reason = "LLM_ENABLED is not true"
        elif not self.settings.llm_api_key:
            reason = "LLM_API_KEY is empty or .env was not loaded"
        return {
            "enabled": self.enabled(),
            "configured": bool(self.settings.llm_api_key),
            "provider": self.settings.llm_provider,
            "model": self.settings.llm_model,
            "fallback_mode": not self.enabled(),
            "reason": reason,
        }

    def _call_openai_compatible(self, transaction: dict, agent_outputs: list[dict], decision: str, risk_score: float) -> str:
        prompt = (
            "你是金融反欺诈系统的协同决策解释 Agent。"
            "请基于交易、多个 Agent 评分和最终决策，输出严格的 JSON 对象，不要输出任何其他文字或代码块标记。\n"
            "字段说明：\n"
            'summary：一句话中文风险摘要（≤50字），只陈述证据中实际出现的风险点，禁止编造；\n'
            'evidence：风险证据列表（2-4 条，每条 ≤30 字），必须来自给定的 Agent 证据，不得虚构；\n'
            'recommendation：给审核员或系统的下一步处置建议（≤60字），须与最终决策一致；\n'
            'audit_note：可审计性说明（≤40字），说明结论所依据的证据来源（如"基于交易分析Agent与行为建模Agent的证据"）。\n\n'
            f"交易: {transaction}\n"
            f"Agent结果: {agent_outputs}\n"
            f"最终决策: {decision}, 风险分: {risk_score}\n\n"
            "输出格式（严格 JSON）：\n"
            '{"summary": "...", "evidence": ["...", "..."], "recommendation": "...", "audit_note": "..."}'
        )
        return self._call_prompt(system="你是金融反欺诈系统的决策解释引擎，只输出可解析的严格 JSON。", user=prompt)

    def _call_prompt(self, *, system: str, user: str, timeout: float | None = None) -> str:
        endpoint = self.settings.llm_api_base.rstrip("/") + "/chat/completions"
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"},
            json={
                "model": self.settings.llm_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            },
            timeout=timeout or self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _fallback(self, *, transaction: dict, agent_outputs: list[dict], decision: str, risk_score: float) -> LLMDecisionInsight:
        strongest = max(agent_outputs, key=lambda item: item.get("risk_score", 0), default={})
        summary = f"{strongest.get('agent_id', '规则引擎')} 给出最高风险证据，综合风险分 {risk_score:.2f}，系统判定为 {decision}。"
        if decision == "BLOCK":
            recommendation = "建议立即拦截交易，生成高优先级案件并保留完整证据链。"
        elif decision == "REVIEW":
            recommendation = "建议进入人工复核，重点核查金额、设备和异地行为证据。"
        else:
            recommendation = "建议放行交易，并保留审计记录用于后续画像更新。"
        return LLMDecisionInsight(
            enabled=False,
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
            summary=summary,
            recommendation=recommendation,
            fallback=True,
        )

    def _security_fallback(self, snapshot: dict) -> dict:
        devices = snapshot.get("devices", [])
        privacy_items = snapshot.get("privacy_items", [])
        mfa = snapshot.get("mfa", {})
        risky_devices = sum(1 for item in devices if not item.get("trusted", True))
        weak_privacy = sum(1 for item in privacy_items if item.get("weak"))
        score = 92 - risky_devices * 12 - weak_privacy * 6
        if not mfa.get("sms_enabled", False):
            score -= 10
        if not mfa.get("face_enabled", False):
            score -= 8
        score = max(40, min(100, score))
        level = "安全" if score >= 85 else "需关注" if score >= 70 else "高风险"
        recommendations = []
        if risky_devices:
            recommendations.append("移除陌生或待核验设备，并重新登录可信设备。")
        if weak_privacy:
            recommendations.append("清理弱授权，仅保留风控必要授权。")
        if not mfa.get("sms_enabled") or not mfa.get("face_enabled"):
            recommendations.append("开启短信动态码与人脸核验，覆盖大额交易和申诉解封。")
        if not recommendations:
            recommendations.append("当前核心防护配置良好，建议保持定期体检。")
        return {
            "score": score,
            "level": level,
            "summary": f"本地安全体检评分 {score}，发现 {risky_devices} 台异常设备、{weak_privacy} 项弱授权。",
            "recommendations": recommendations,
            "llm": self.status(),
            "fallback": True,
        }

    @staticmethod
    def _parse_explanation(content: str) -> dict | None:
        """解析 LLM 决策解释输出。容忍 ```json 代码块包裹、前后空白与多余文字。

        返回 {"summary", "evidence", "recommendation", "audit_note"}；
        结构不合法（缺字段 / 类型错误 / 非 JSON）时返回 None，调用方回退规则模板。
        """
        text = content.strip()
        if text.startswith("```"):
            if text.count("```") >= 2:
                text = text.split("```", 2)[1]
            else:
                text = text[3:]
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        summary = data.get("summary")
        recommendation = data.get("recommendation")
        if not isinstance(summary, str) or not summary.strip():
            return None
        if not isinstance(recommendation, str) or not recommendation.strip():
            return None
        evidence = data.get("evidence")
        if evidence is not None and (not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence)):
            return None
        audit_note = data.get("audit_note")
        if audit_note is not None and not isinstance(audit_note, str):
            return None
        return {
            "summary": summary.strip(),
            "recommendation": recommendation.strip(),
            "evidence": [item.strip() for item in (evidence or [])],
            "audit_note": (audit_note or "").strip(),
        }
