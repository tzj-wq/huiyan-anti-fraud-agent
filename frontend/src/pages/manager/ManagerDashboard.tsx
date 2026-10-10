import { useEffect, useState } from "react";
import { Section } from "../../components/Section";
import { StatCard } from "../../components/StatCard";
import { MiniChart } from "../../components/MiniChart";
import { DecisionTimeline } from "../../components/DecisionTimeline";
import { api } from "../../services/api";

export function ManagerDashboard() {
  const [metrics, setMetrics] = useState<any>();
  const [alerts, setAlerts] = useState<any[]>([]);
  const [sampleResult, setSampleResult] = useState<any>();

  useEffect(() => {
    api.metrics().then(setMetrics);
    api.alerts().then(setAlerts);
  }, []);

  async function runSample(kind: "pass" | "review" | "block" | "conflict") {
    const payloads = {
      pass: { user_id: "U1001", amount: 1200, channel: "APP", device_id: "DEV-1001", merchant_id: "MCH-NORMAL-001", location: "上海" },
      review: { user_id: "U2002", amount: 368000, channel: "APP", device_id: "DEV-2002", merchant_id: "MCH-NORMAL-001", location: "哈尔滨", night_operation: true },
      block: { user_id: "U9009", amount: 1240000, channel: "WEB", device_id: "DEV-RISK-X", merchant_id: "MCH-RISK-001", location: "上海" },
      conflict: { user_id: "U3003", amount: 3000, channel: "私人转账", device_id: "DEV-2002", merchant_id: "MCH-NORMAL-001", location: "北京", night_operation: true }
    };
    const result = await api.detect(payloads[kind]);
    setSampleResult(result);
    setMetrics(await api.metrics());
    setAlerts(await api.alerts());
  }

  return (
    <div className="page">
      <div className="page-title">
        <h1>实时风险看板</h1>
        <p>交易检测、告警分布、Agent 状态和处置建议的统一视图</p>
      </div>
      <div className="stats-grid">
        <StatCard label="交易总量" value={metrics?.kpis.transactions ?? "--"} />
        <StatCard label="告警总数" value={metrics?.kpis.alerts ?? "--"} tone="red" />
        <StatCard label="待处理案件" value={metrics?.kpis.pending_cases ?? "--"} tone="amber" />
        <StatCard label="生效名单项" value={metrics?.kpis.risk_items ?? "--"} tone="green" />
      </div>
      <Section
        title="演示交易检测"
        action={
          <div className="button-row">
            <button onClick={() => runSample("pass")}>低风险 PASS</button>
            <button onClick={() => runSample("review")}>中风险 REVIEW</button>
            <button className="danger" onClick={() => runSample("block")}>高危 BLOCK</button>
            <button onClick={() => runSample("conflict")}>冲突消解</button>
          </div>
        }
      >
        {sampleResult ? (
          <div className="result-box">
            <strong>{sampleResult.decision}</strong>
            <span>风险分 {sampleResult.risk_score} · LLM {sampleResult.llm?.enabled ? "已启用" : "本地回退"} · 告警 {sampleResult.alert?.alert_id ?? "无"}</span>
            <p>{sampleResult.evidence_summary}</p>
            <p>{sampleResult.recommendation}</p>
            <div className="decision-timeline-wrap">
              <h4>协同决策过程</h4>
              <DecisionTimeline collaboration={sampleResult.collaboration} />
            </div>
          </div>
        ) : (
          <p className="muted">点击上方样本交易，系统会并行调用 6 个 Agent（5 规则 + 1 LLM 语义）独立评估，冲突时触发仲裁并融合决策。</p>
        )}
      </Section>
      <div className="dashboard-grid">
        <Section title="决策分布">
          <MiniChart data={metrics?.decision_distribution ?? []} type="pie" />
        </Section>
        <Section title="Agent 平均延迟">
          <MiniChart data={(metrics?.agent_latency ?? []).map((item: any) => ({ name: item.agent_id.replace("-", "\n"), value: item.avg_ms }))} />
        </Section>
        <section className="dark-panel">
          <div className="section-header">
            <h2>最新高危告警</h2>
            <span>准实时</span>
          </div>
          <div className="dark-list">
            {alerts.slice(0, 5).map((alert) => (
              <div className="dark-row" key={alert.alert_id}>
                <span>{alert.title}<small>{alert.trace_id}</small></span>
                <strong className={`badge ${alert.level}`}>{alert.level}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
