const actionLabel: Record<string, string> = {
  UPWEIGHT: "升权",
  DOWNWEIGHT: "降权",
  EXCLUDE: "剔除"
};

const reasonLabel: Record<string, string> = {
  CONFLICT: "意见冲突",
  BORDERLINE: "阈值边界",
  DEGRADED: "Agent 降级"
};

const escalationLabel: Record<string, string> = {
  NONE: "维持融合结论",
  ESCALATE_REVIEW: "升级人工复核",
  ESCALATE_BLOCK: "升级拦截"
};

function pct(value: number) {
  return `${Math.max(2, Math.round(Math.min(1, Math.max(0, value)) * 100))}%`;
}

export function DecisionTimeline({ collaboration }: { collaboration?: any }) {
  const rounds: any[] = collaboration?.rounds ?? [];
  const fusion = collaboration?.fusion;
  const stageMs = collaboration?.stage_ms;
  if (!rounds.length) return null;
  const totalContribution = (fusion?.contributions ?? []).reduce((sum: number, item: any) => sum + (item.contribution ?? 0), 0);

  return (
    <div className="decision-timeline client-timeline">
      {rounds.map((round: any) => (
        <article className="done" key={round.round_id}>
          <span />
          <div>
            <strong>
              第 {round.round_id} 轮 · {round.name}
              {round.round_id === 2 && (
                <em className={`decision-method ${round.method}`}>
                  {round.method === "llm" ? "LLM 仲裁" : "规则仲裁"}
                </em>
              )}
            </strong>
            {round.round_id === 1 ? (
              <div className="decision-agents">
                {(round.agents ?? []).map((agent: any) => (
                  <div key={agent.agent_id} className={agent.degraded ? "degraded" : ""}>
                    <span>{agent.agent_id}</span>
                    <div><i style={{ width: pct(agent.risk_score) }} /></div>
                    <em>{agent.risk_score}</em>
                    <small>{agent.degraded ? "已降级" : `置信 ${agent.confidence}`}</small>
                  </div>
                ))}
              </div>
            ) : (
              <div className="decision-arbitration">
                <p>{round.rationale}</p>
                <p className="decision-meta">
                  触发原因：{reasonLabel[round.reason] ?? round.reason} · 处置：{escalationLabel[round.escalation] ?? round.escalation}
                  {round.conflict ? ` · 分歧幅度 ${round.conflict.spread}` : ""}
                </p>
                {!!round.adjustments?.length && (
                  <div className="decision-adjustments">
                    {round.adjustments.map((item: any) => (
                      <span key={item.agent_id}>
                        {item.agent_id}：{item.confidence_before} → {item.confidence_after}（{actionLabel[item.action] ?? item.action}）
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </article>
      ))}
      {fusion && (
        <article className="done">
          <span />
          <div>
            <strong>融合决策 · {fusion.method === "confidence-weighted" ? "置信度加权" : fusion.method}</strong>
            <div className="decision-agents">
              {(fusion.contributions ?? []).map((item: any) => (
                <div key={item.agent_id}>
                  <span>{item.agent_id}</span>
                  <div><i style={{ width: totalContribution ? pct(item.contribution / totalContribution) : "0%" }} /></div>
                  <em>{item.score}</em>
                  <small>权重 {item.effective_weight}</small>
                </div>
              ))}
            </div>
            <p className="decision-meta">
              最终风险分 <strong>{fusion.final_score}</strong>
              {fusion.quorum_failure ? " · 有效 Agent 不足，保守处理" : ""}
              {stageMs ? ` · 用时 ${stageMs.total_ms}ms（评估 ${stageMs.stage1_ms} / 仲裁 ${stageMs.stage2_ms}）` : ""}
            </p>
          </div>
        </article>
      )}
    </div>
  );
}
