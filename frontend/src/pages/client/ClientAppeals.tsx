import { FileText, Gavel, Paperclip, RefreshCw, ShieldAlert, TimerReset, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../services/api";

const statusText: Record<string, string> = {
  SUBMITTED: "已提交",
  NEED_SUPPLEMENT: "需补充",
  APPROVED: "申诉通过",
  REJECTED: "申诉驳回",
  COMPLETED: "已完成"
};

const defaultMaterials = ["交易凭证", "聊天记录截图", "本人身份核验"];

export function ClientAppeals() {
  const [transactions, setTransactions] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>();
  const [flowTarget, setFlowTarget] = useState<any>();
  const [reason, setReason] = useState("该交易为本人真实交易，收款对象与交易金额可核实，请人工复核解除拦截。");
  const [materials, setMaterials] = useState(defaultMaterials);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const activeCount = useMemo(
    () => transactions.filter((item) => item.appeal && !["APPROVED", "REJECTED", "COMPLETED"].includes(item.appeal.status)).length,
    [transactions]
  );

  async function load() {
    setLoading(true);
    setError("");
    try {
      setTransactions(await api.appealableTransactions("U2002"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "异常交易加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openAppeal(row: any) {
    setSelected(row);
    setReason(row.appeal?.reason || "该交易为本人真实交易，收款对象与交易金额可核实，请人工复核解除拦截。");
    setMaterials(row.appeal?.materials?.length ? row.appeal.materials : defaultMaterials);
  }

  async function submitAppeal() {
    if (!selected) return;
    setLoading(true);
    setError("");
    try {
      await api.submitAppeal({
        transaction_id: selected.transaction_id,
        user_id: selected.user_id,
        reason,
        materials
      });
      setSelected(undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "申诉提交失败");
    } finally {
      setLoading(false);
    }
  }

  function addMaterial() {
    setMaterials((items) => [...items, `补充材料 ${items.length + 1}`]);
  }

  return (
    <div className="client-page">
      <div className="client-title">
        <div>
          <h1>申诉处理中心</h1>
          <p>选择异常交易发起误拦申诉，处理流程会同步到后台案件审理。</p>
        </div>
        <button className="client-secondary-button" onClick={load} disabled={loading}><RefreshCw size={16} />刷新</button>
      </div>

      {error && <p className="client-error">{error}</p>}

      <section className="client-panel">
        <div className="client-panel-head">
          <div>
            <h2>异常交易列表</h2>
            <p>仅展示已进入 REVIEW 或 BLOCK 的交易；PASS 交易无需申诉。</p>
          </div>
          <ShieldAlert />
        </div>
        <div className="client-appeal-table">
          <div className="head"><span>交易号</span><span>场景</span><span>金额</span><span>决策</span><span>申诉状态</span><span>操作</span></div>
          {transactions.map((row) => (
            <div key={row.transaction_id}>
              <span>{row.transaction_id}<small>{row.user_id} · {row.location || "未知地点"}</small></span>
              <span>{row.channel}<small>{row.counterparty_type || "未提供对象"}</small></span>
              <span>{Number(row.amount).toLocaleString("zh-CN")}</span>
              <strong className={`badge ${String(row.decision).toLowerCase()}`}>{row.decision}</strong>
              <span>{row.appeal ? statusText[row.appeal.status] || row.appeal.status : "未申诉"}</span>
              <span className="client-appeal-actions">
                <button onClick={() => openAppeal(row)}>{row.appeal ? "编辑申诉" : "发起申诉"}</button>
                {row.appeal && <button className="client-secondary-button" onClick={() => setFlowTarget(row)}>查看流程</button>}
              </span>
            </div>
          ))}
          {!transactions.length && <p className="muted">{loading ? "正在加载异常交易..." : "暂无可申诉的异常交易。请先在交易评估中提交 REVIEW/BLOCK 样例。"}</p>}
        </div>
      </section>

      <div className="client-grid">
        <article className="client-card"><TimerReset /><h3>进行中的申诉</h3><p>已提交但尚未完成后台复核的申诉数量。</p><strong>{activeCount} 单</strong></article>
        <article className="client-card"><Gavel /><h3>后台案件联动</h3><p>申诉材料会进入案件证据链，由管理端复核处理。</p><strong>已打通</strong></article>
        <article className="client-card"><FileText /><h3>申诉材料建议</h3><p>请补充交易凭证、聊天记录和身份核验材料。</p><strong>3 类</strong></article>
      </div>

      {selected && (
        <div className="client-modal-backdrop">
          <section className="client-modal">
            <div className="client-modal-head">
              <div>
                <h2>编辑申诉</h2>
                <p>{selected.transaction_id} · 风险分 {selected.risk_score}</p>
              </div>
              <button className="client-icon-button" onClick={() => setSelected(undefined)}><X size={18} /></button>
            </div>
            <div className="client-appeal-summary">
              <span>金额 {Number(selected.amount).toLocaleString("zh-CN")}</span>
              <span>{selected.channel}</span>
              <span>{selected.counterparty_type || "未提供对象"}</span>
              <span>{selected.decision}</span>
            </div>
            <label className="client-field">申诉说明
              <textarea value={reason} onChange={(event) => setReason(event.target.value)} />
            </label>
            <div className="client-material-list">
              {materials.map((item, index) => (
                <article key={`${item}-${index}`}><Paperclip size={16} /><span>{item}</span><strong>已添加</strong></article>
              ))}
            </div>
            <div className="client-action-grid">
              <button className="client-secondary-button" onClick={addMaterial}>补充材料</button>
              <button onClick={submitAppeal} disabled={loading}>{loading ? "提交中..." : "提交申诉"}</button>
            </div>
          </section>
        </div>
      )}

      {flowTarget && (
        <div className="client-modal-backdrop">
          <section className="client-modal narrow">
            <div className="client-modal-head">
              <div>
                <h2>处理流程</h2>
                <p>{flowTarget.appeal?.appeal_id} · {statusText[flowTarget.appeal?.status] || flowTarget.appeal?.status}</p>
              </div>
              <button className="client-icon-button" onClick={() => setFlowTarget(undefined)}><X size={18} /></button>
            </div>
            <div className="client-timeline">
              {(flowTarget.appeal?.timeline ?? []).map((item: any, index: number) => (
                <article className="done" key={`${item.title}-${index}`}><span /> <div><strong>{item.title}</strong><p>{item.detail}</p></div></article>
              ))}
              {flowTarget.appeal?.handler_note && (
                <article className="done"><span /> <div><strong>后台处理意见</strong><p>{flowTarget.appeal.handler_note}</p></div></article>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
