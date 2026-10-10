"""LangGraph 检测工作流：将阶段1的协同决策升级为显式状态图编排。

图结构：
    START → run_agents（并行 6 Agent，独立超时）
          → analyze_conflict → 条件路由（needs_arbitration → arbitrate / skip）
          → fuse_decide（置信度加权融合 + 决策 + trace）→ END

输出结构与原 _collaborative_decide 完全一致；detect_transaction 默认经此图执行，
异常时回退原实现（安全兜底，不中断风控链路）。
"""
from __future__ import annotations

from time import perf_counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.llm import LLMClient
from app.modules.detection.agents import AGENTS, AgentOutput
from app.modules.detection.collaboration import (
    ArbitrationVerdict,
    analyze_conflict,
    arbitrate,
    build_fusion_stage,
    build_stage1,
    build_stage2,
    decide,
    fuse,
)

AGENT_TIMEOUT_SECONDS = 0.3
DEGRADED_CONFIDENCE = 0.2


class DetectState(TypedDict):
    payload: dict
    features: dict
    strategy: object
    outputs: list
    report: object
    verdict: object
    stage1_ms: int
    stage2_ms: int
    decision: str
    risk_score: float
    conflict_flag: bool
    trace: dict
    timings: dict


def _degraded_output(agent_id: str, agent_type: str) -> AgentOutput:
    return AgentOutput(
        agent_id=agent_id,
        agent_type=agent_type,
        risk_score=0.8,
        risk_label="AGENT_TIMEOUT",
        evidence=[{"summary": "Agent 超时，已从融合中剔除并保守处理", "score": 0.8}],
        exec_time_ms=int(AGENT_TIMEOUT_SECONDS * 1000),
        degraded=True,
        confidence=DEGRADED_CONFIDENCE,
    )


def _run_agents_parallel(payload: dict, features: dict) -> list[AgentOutput]:
    """并行运行全部检测 Agent，按各自 timeout_seconds 独立等待（规则 Agent 0.3s，LLM 语义 Agent 3.5s）。

    超时或异常统一转为降级输出（degraded=True），由仲裁阶段剔除，不注入保守分。
    """
    from concurrent.futures import ThreadPoolExecutor

    outputs: list[AgentOutput] = []
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as executor:
        future_map = {executor.submit(agent.analyze, payload, features): agent for agent in AGENTS}
        for future, agent in future_map.items():
            try:
                outputs.append(future.result(timeout=agent.timeout_seconds))
            except TimeoutError:
                future.cancel()
                outputs.append(_degraded_output(agent.agent_id, agent.agent_type))
            except Exception:
                outputs.append(_degraded_output(agent.agent_id, agent.agent_type))
    return sorted(outputs, key=lambda output: output.agent_id)


def _node_run_agents(state: DetectState) -> dict:
    started = perf_counter()
    outputs = _run_agents_parallel(state["payload"], state["features"])
    return {"outputs": outputs, "stage1_ms": max(1, int((perf_counter() - started) * 1000))}


def _node_analyze_conflict(state: DetectState) -> dict:
    return {"report": analyze_conflict(state["outputs"], state["strategy"])}


def _route_arbitration(state: DetectState) -> str:
    return "arbitrate" if state["report"].needs_arbitration else "skip"


def _node_arbitrate(state: DetectState) -> dict:
    started = perf_counter()
    verdict = arbitrate(
        state["payload"],
        state["outputs"],
        state["report"],
        state["strategy"],
        llm_client=LLMClient(),
    )
    return {"verdict": verdict, "stage2_ms": max(0, int((perf_counter() - started) * 1000))}


def _node_skip_arbitration(state: DetectState) -> dict:
    return {"verdict": ArbitrationVerdict.not_triggered(), "stage2_ms": 0}


def _node_fuse_decide(state: DetectState) -> dict:
    verdict = state["verdict"]
    fusion = fuse(state["outputs"], state["strategy"].agent_weights, verdict)
    decision = decide(state["outputs"], fusion, verdict, state["strategy"])
    rounds = [build_stage1(state["outputs"])]
    if verdict.triggered:
        rounds.append(build_stage2(state["report"], verdict))
    trace = {
        "rounds": rounds,
        "fusion": build_fusion_stage(fusion, verdict),
        "conflict": {
            "has_conflict": state["report"].has_conflict,
            "spread": state["report"].spread,
            "median_score": state["report"].median_score,
            "trigger_reason": state["report"].trigger_reason,
        },
    }
    timings = {
        "stage1_ms": state["stage1_ms"],
        "stage2_ms": state["stage2_ms"],
        "total_ms": state["stage1_ms"] + state["stage2_ms"],
    }
    return {
        "decision": decision,
        "risk_score": fusion.risk_score,
        "conflict_flag": state["report"].has_conflict,
        "trace": trace,
        "timings": timings,
    }


_DETECT_GRAPH = None


def _detect_graph():
    global _DETECT_GRAPH
    if _DETECT_GRAPH is None:
        graph = StateGraph(DetectState)
        graph.add_node("run_agents", _node_run_agents)
        graph.add_node("analyze_conflict", _node_analyze_conflict)
        graph.add_node("arbitrate", _node_arbitrate)
        graph.add_node("skip", _node_skip_arbitration)
        graph.add_node("fuse_decide", _node_fuse_decide)
        graph.add_edge(START, "run_agents")
        graph.add_edge("run_agents", "analyze_conflict")
        graph.add_conditional_edges(
            "analyze_conflict",
            _route_arbitration,
            {"arbitrate": "arbitrate", "skip": "skip"},
        )
        graph.add_edge("arbitrate", "fuse_decide")
        graph.add_edge("skip", "fuse_decide")
        graph.add_edge("fuse_decide", END)
        _DETECT_GRAPH = graph.compile()
    return _DETECT_GRAPH


def detect_via_langgraph(payload: dict, features: dict, strategy) -> tuple[str, float, bool, list[AgentOutput], dict, dict]:
    """经 LangGraph 图执行检测工作流，返回与 _collaborative_decide 同构的六元组。"""
    state = _detect_graph().invoke(
        {
            "payload": payload,
            "features": features,
            "strategy": strategy,
            "stage1_ms": 0,
            "stage2_ms": 0,
        },
        config={"recursion_limit": 20},
    )
    return (
        state["decision"],
        state["risk_score"],
        state["conflict_flag"],
        state["outputs"],
        state["trace"],
        state["timings"],
    )
