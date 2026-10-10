import { AlertTriangle, Bot, CheckCircle2, CreditCard, Gavel, Search, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../services/api";
import { loadLoginDevices } from "../../services/clientState";

const channelOptions = ["线下当面交易", "网络平台", "私人转账", "其他渠道"];
const targetOptions = ["网络电商", "个人卖家", "对公转账", "对私转账（陌生人）", "对私转账（熟人）"];

const targetRiskMap: Record<string, string> = {
  "网络电商": "MCH-ECOMMERCE-001",
  "个人卖家": "MCH-SELLER-001",
  "对公转账": "MCH-CORP-001",
  "对私转账（陌生人）": "MCH-RISK-001",
  "对私转账（熟人）": "MCH-FRIEND-001"
};

const initialForm = {
  user_id: "U2002",
  amount: "368000",
  channel: "网络平台",
  device_id: "DEV-WINDOWS-PC",
  target_type: "对私转账（陌生人）",
  location: "哈尔滨",
  night_operation: true
};

export function ClientTransaction() {
  const devices = useMemo(() => loadLoginDevices(), []);
  const [form, setForm] = useState({ ...initialForm, device_id: devices[0]?.value ?? initialForm.device_id });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>();
  const [records, setRecords] = useState<any[]>([]);
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    loadRecords();
  }, []);

  function update(field: keyof typeof form, value: string | boolean) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function loadRecords(nextKeyword = keyword) {
    setRecords(await api.transactions(nextKeyword));
  }

  async function submit() {
    setLoading(true);
    setError("");
    try {
      const data = await api.detect({
        ...form,
        amount: Number(form.amount),
        merchant_id: targetRiskMap[form.target_type],
        counterparty_type: form.target_type
      });
      setResult(data);
      await loadRecords("");
      setKeyword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "交易评估失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="client-page">
      <div className="client-title">
        <div>
          <h1>提交交易记录</h1>
          <p>从渠道、设备、交易对象、行为与大模型解释多个维度评估风险。</p>
        </div>
      </div>
      <div className="client-transaction-layout">
        <section className="client-panel">
          <div className="client-panel-head">
            <div>
              <h2>交易信息</h2>
              <p>选择交易场景模拟不同风险组合。</p>
            </div>
            <CreditCard />
          </div>
          <div className="client-form-grid">
            <label>用户ID<input value={form.user_id} onChange={(event) => update("user_id", event.target.value)} /></label>
            <label>交易金额<input value={form.amount} onChange={(event) => update("amount", event.target.value)} /></label>
            <label>交易渠道
              <select value={form.channel} onChange={(event) => update("channel", event.target.value)}>
                {channelOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>登录设备
              <select value={form.device_id} onChange={(event) => update("device_id", event.target.value)}>
                {devices.map((device) => <option key={device.id} value={device.value}>{device.name} · {device.location}</option>)}
              </select>
            </label>
            <label>交易对象
              <select value={form.target_type} onChange={(event) => update("target_type", event.target.value)}>
                {targetOptions.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>交易地点<input value={form.location} onChange={(event) => update("location", event.target.value)} /></label>
            <label className="client-checkbox">
              <input type="checkbox" checked={form.night_operation} onChange={(event) => update("night_operation", event.target.checked)} />
              夜间/异常时段操作
            </label>
          </div>
          <button onClick={submit} disabled={loading}>{loading ? "评估中..." : "提交交易评估"}</button>
          {error && <p className="client-error">{error}</p>}
        </section>

        <section className="client-panel">
          <div className="client-panel-head">
            <div>
              <h2>风险评估结果</h2>
              <p>包含协同 Agent 评分和大模型解释。</p>
            </div>
            {result?.decision === "PASS" ? <CheckCircle2 /> : <ShieldAlert />}
          </div>
          {!result ? (
            <div className="client-empty-result">
              <Bot size={36} />
              <span>提交后将在这里展示多维评估结果。</span>
            </div>
          ) : (
            <div className="client-risk-result">
              <div className={`client-decision ${result.decision.toLowerCase()}`}>
                <strong>{result.decision}</strong>
                <span>风险分 {result.risk_score} · Agent {result.agent_count} 个 · 冲突 {result.conflict_flag ? "是" : "否"}</span>
              </div>
              <article>
                <h3><Bot size={18} />大模型/解释 Agent</h3>
                <p>{result.evidence_summary}</p>
                <p>{result.recommendation}</p>
                <em>{result.llm?.enabled ? "智能解释已启用" : "当前为本地回退解释，请检查 .env 与后端重启状态"}</em>
              </article>
              <article>
                <h3><AlertTriangle size={18} />风险标签</h3>
                <div className="client-tag-row">
                  {(result.risk_labels ?? []).map((label: string) => <span key={label}>{label}</span>)}
                </div>
              </article>
              {result.collaboration?.rounds?.length > 1 && (
                <article className="client-arbitration">
                  <h3><Gavel size={18} />协同仲裁</h3>
                  <p>{result.collaboration.rounds[1]?.rationale}</p>
                </article>
              )}
              <article>
                <h3>多维 Agent 评分</h3>
                <div className="client-agent-bars">
                  {(result.agent_results ?? []).map((agent: any) => (
                    <div key={agent.agent_id} className={agent.degraded ? "degraded" : ""}>
                      <span>{agent.agent_id}</span>
                      <div><i style={{ width: `${Math.round(agent.risk_score * 100)}%` }} /></div>
                      <strong>{agent.risk_score}</strong>
                      <small>{agent.degraded ? "降级" : `置信 ${agent.confidence}`}</small>
                    </div>
                  ))}
                </div>
              </article>
            </div>
          )}
        </section>
      </div>

      <section className="client-panel">
        <div className="client-panel-head">
          <div>
            <h2>交易记录查询</h2>
            <p>查询已提交交易的风险评分、决策与证据摘要。</p>
          </div>
          <div className="client-record-search">
            <Search size={16} />
            <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索用户、交易号、渠道、对象" />
            <button onClick={() => loadRecords(keyword)}>查询</button>
          </div>
        </div>
        <div className="client-record-table">
          <div className="head"><span>交易号</span><span>渠道/对象</span><span>金额</span><span>决策</span><span>风险分</span></div>
          {records.map((record) => (
            <div key={record.transaction_id}>
              <span>{record.transaction_id}<small>{record.user_id}</small></span>
              <span>{record.channel}<small>{record.raw_payload?.counterparty_type ?? record.merchant_id}</small></span>
              <span>{Number(record.amount).toLocaleString("zh-CN")}</span>
              <strong className={`badge ${String(record.decision).toLowerCase()}`}>{record.decision}</strong>
              <span>{record.risk_score}</span>
            </div>
          ))}
          {!records.length && <p className="muted">暂无交易记录。</p>}
        </div>
      </section>
    </div>
  );
}
