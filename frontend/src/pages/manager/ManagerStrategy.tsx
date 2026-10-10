import { useEffect, useState } from "react";
import { Section } from "../../components/Section";
import { MiniChart } from "../../components/MiniChart";
import { api, DEMO_CONFIRM_TOKEN } from "../../services/api";

export function ManagerStrategy() {
  const [strategy, setStrategy] = useState<any>();
  const [llm, setLlm] = useState<any>();
  const [learning, setLearning] = useState<any>();
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.strategy().then(setStrategy);
    api.llmStatus().then(setLlm);
    api.learning().then(setLearning).catch(() => setLearning(undefined));
  }, []);

  async function reloadLearning() {
    setLearning(await api.learning().catch(() => undefined));
  }

  async function publish() {
    const payload = {
      ...strategy,
      name: "MVP 演示策略",
      confirm_token: DEMO_CONFIRM_TOKEN
    };
    const validation = await api.validateStrategy(payload);
    if (!validation.valid) {
      setMessage(validation.message);
      return;
    }
    const next = await api.publishStrategy(payload);
    setStrategy(next);
    setMessage("策略发布成功，审计日志已写入。");
  }

  async function adoptLearned() {
    try {
      const next = await api.adoptLearned(DEMO_CONFIRM_TOKEN);
      setStrategy(next);
      setMessage("学习权重已采纳，新策略版本已发布并写入审计。");
      await reloadLearning();
    } catch (err) {
      setMessage(err instanceof Error ? "采纳失败" : "采纳失败");
    }
  }

  function updateWeight(agent: string, value: number) {
    setStrategy({
      ...strategy,
      agent_weights: {
        ...strategy.agent_weights,
        [agent]: value
      }
    });
  }

  const totalFeedback = (learning?.agents ?? []).reduce((sum: number, agent: any) => sum + (agent.total_samples ?? 0), 0);
  const hasLearning = totalFeedback > 0;
  const maxHistory = Math.max(0, ...(learning?.agents ?? []).map((agent: any) => agent.recent_history?.length ?? 0));
  const ewmaLabels = Array.from({ length: maxHistory }, (_, index) => `第${index + 1}次`);
  const ewmaSeries = (learning?.agents ?? [])
    .filter((agent: any) => (agent.recent_history ?? []).length > 0)
    .map((agent: any) => ({
      name: agent.agent_id,
      data: agent.recent_history.map((item: any) => item.ewma_after)
    }));

  return (
    <div className="page">
      <div className="page-title">
        <h1>策略配置中心</h1>
        <p>Agent 权重、冲突阈值、规则校验、发布与学习权重采纳的统一入口</p>
      </div>
      <Section title="当前策略" action={<button onClick={publish}>发布新版本</button>}>
        {llm && (
          <div className="llm-strip">
            <strong>大模型增强</strong>
            <span>{llm.enabled ? "已启用真实调用" : "未启用，当前使用本地回退解释"}</span>
            <code>{llm.provider} · {llm.model}</code>
          </div>
        )}
        {strategy && (
          <div className="strategy-grid">
            <label>冲突阈值<input type="number" step="0.05" value={strategy.conflict_threshold} onChange={(e) => setStrategy({ ...strategy, conflict_threshold: Number(e.target.value) })} /></label>
            <label>复核阈值<input type="number" step="0.05" value={strategy.review_threshold} onChange={(e) => setStrategy({ ...strategy, review_threshold: Number(e.target.value) })} /></label>
            <label>拦截阈值<input type="number" step="0.05" value={strategy.block_threshold} onChange={(e) => setStrategy({ ...strategy, block_threshold: Number(e.target.value) })} /></label>
            <div className="agent-weight-editor">
              {Object.entries(strategy.agent_weights ?? {}).map(([agent, weight]) => (
                <label key={agent}>
                  <span>{agent}</span>
                  <input type="number" step="0.01" value={Number(weight)} onChange={(event) => updateWeight(agent, Number(event.target.value))} />
                </label>
              ))}
            </div>
            <pre>{JSON.stringify(strategy.agent_weights, null, 2)}</pre>
          </div>
        )}
        {message && <p className="notice">{message}</p>}
      </Section>

      <Section
        title="Agent 表现与学习权重（反馈闭环）"
        action={
          <button onClick={adoptLearned} disabled={!hasLearning}>
            采纳学习权重
          </button>
        }
      >
        {!learning ? (
          <p className="muted">学习统计加载中或暂不可用。</p>
        ) : !hasLearning ? (
          <p className="muted">
            暂无反馈样本。在案件工作台完成复核（欺诈/误报/待观察）后，系统会把各 Agent 的历史评分与人工结论比对，
            通过 EWMA + 贝叶斯收缩 + softmax 自动更新学习权重。
          </p>
        ) : (
          <>
            <div className="learning-ready-strip">
              <span>
                已累计 {totalFeedback} 条 Agent 反馈信号
                {learning.ready ? " · 样本充足，可采纳" : ` · 建议每 Agent 不少于 ${learning.min_ready_samples} 条后采纳`}
              </span>
              <code>EWMA α={learning.ewma_alpha} · 先验={learning.prior_accuracy}</code>
            </div>
            <div className="learning-table">
              <div className="head"><span>Agent</span><span>配置权重</span><span>学习权重</span><span>样本数</span><span>收缩准确率</span></div>
              {(learning.agents ?? []).map((agent: any) => (
                <div key={agent.agent_id}>
                  <span>{agent.agent_id}</span>
                  <span>{agent.configured_weight}</span>
                  <strong>{agent.learned_weight}</strong>
                  <span>{agent.total_samples}</span>
                  <span>{agent.shrunk_accuracy ?? "--"}</span>
                </div>
              ))}
            </div>
            {ewmaSeries.length > 0 && (
              <div className="learning-chart">
                <h4>各 Agent EWMA 准确率演进（最近 {maxHistory} 次复核）</h4>
                <MiniChart type="line" series={ewmaSeries} labels={ewmaLabels} height={260} />
              </div>
            )}
          </>
        )}
      </Section>
    </div>
  );
}
