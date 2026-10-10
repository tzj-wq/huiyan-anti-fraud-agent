import { FileText, Gavel, MessageSquareWarning, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Section } from "../../components/Section";
import { StatCard } from "../../components/StatCard";
import { DecisionTimeline } from "../../components/DecisionTimeline";
import { api, DEMO_CONFIRM_TOKEN } from "../../services/api";

const statusLabel: Record<string, string> = {
  PENDING: "待审理",
  APPEALED: "用户申诉",
  NEED_SUPPLEMENT: "需补充",
  COMPLETED: "已完成"
};

const appealStatusLabel: Record<string, string> = {
  SUBMITTED: "已提交",
  NEED_SUPPLEMENT: "需补充",
  APPROVED: "申诉通过",
  REJECTED: "申诉驳回",
  COMPLETED: "已完成"
};

const adviceMeta: Record<string, { label: string; className: string }> = {
  REVIEW_CONFIRM: { label: "确认复核风险", className: "reco-danger" },
  RELEASE: { label: "建议放行", className: "reco-safe" },
  ESCALATE: { label: "升级人工复核", className: "reco-amber" }
};

const adviceToResult: Record<string, string> = {
  REVIEW_CONFIRM: "欺诈",
  RELEASE: "误报",
  ESCALATE: "需补充"
};

export function ManagerCases() {
  const [cases, setCases] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>();
  const [evidence, setEvidence] = useState<any>();
  const [process, setProcess] = useState<any>();
  const [advice, setAdvice] = useState<any>();
  const [remark, setRemark] = useState("已核验证据链、用户申诉材料与交易上下文，处理意见如下。");
  const [filter, setFilter] = useState("ALL");
  const [keyword, setKeyword] = useState("");

  async function load(nextSelectedId?: string) {
    const rows = await api.cases();
    setCases(rows);
    const next = rows.find((row) => row.case_id === nextSelectedId) || rows[0];
    if (next) {
      setSelected(next);
      setEvidence(await api.evidence(next.case_id));
      setProcess(await api.decisionProcess(next.transaction.transaction_id).catch(() => null));
      loadAdvice(next.case_id);
    } else {
      setSelected(undefined);
      setEvidence(undefined);
      setProcess(undefined);
      setAdvice(undefined);
    }
  }

  async function loadAdvice(caseId: string) {
    setAdvice(undefined);
    api.reviewAdvice(caseId).then(setAdvice).catch(() => setAdvice(undefined));
  }

  useEffect(() => {
    load();
  }, []);

  async function openCase(row: any) {
    setSelected(row);
    setEvidence(await api.evidence(row.case_id));
    setProcess(await api.decisionProcess(row.transaction.transaction_id).catch(() => null));
    loadAdvice(row.case_id);
    setRemark(row.appeal?.handler_note || row.remark || "已核验证据链、用户申诉材料与交易上下文，处理意见如下。");
  }

  async function submit(review_result: string) {
    if (!selected) return;
    await api.reviewCase({ case_id: selected.case_id, review_result, remark, confirm_token: DEMO_CONFIRM_TOKEN });
    await load(selected.case_id);
  }

  const visibleCases = useMemo(() => {
    return cases.filter((row) => {
      const text = [
        row.case_id,
        row.transaction.user_id,
        row.transaction.transaction_id,
        row.transaction.counterparty_type,
        row.status,
        row.priority,
        row.appeal?.appeal_id,
        row.appeal?.reason
      ].join(" ").toLowerCase();
      const keywordHit = !keyword || text.includes(keyword.toLowerCase());
      const filterHit =
        filter === "ALL" ||
        (filter === "P0" && row.priority === "P0") ||
        (filter === "PENDING" && row.status === "PENDING") ||
        (filter === "APPEALED" && row.status === "APPEALED") ||
        (filter === "NEED_SUPPLEMENT" && row.status === "NEED_SUPPLEMENT") ||
        (filter === "COMPLETED" && row.status === "COMPLETED");
      return keywordHit && filterHit;
    });
  }, [cases, filter, keyword]);

  const metrics = useMemo(() => ({
    appealed: cases.filter((item) => item.status === "APPEALED").length,
    pending: cases.filter((item) => ["PENDING", "APPEALED", "NEED_SUPPLEMENT"].includes(item.status)).length,
    p0: cases.filter((item) => item.priority === "P0").length
  }), [cases]);

  return (
    <div className="page">
      <div className="page-title manager-case-title">
        <div>
          <h1>案件审理工作台</h1>
          <p>案件队列、用户申诉、证据链和人工复核反馈闭环</p>
        </div>
        <button onClick={() => load(selected?.case_id)}><RefreshCw size={16} />刷新</button>
      </div>

      <div className="stats-grid">
        <StatCard label="待处理案件" value={metrics.pending} tone="amber" />
        <StatCard label="用户申诉" value={metrics.appealed} />
        <StatCard label="P0 优先级" value={metrics.p0} tone="red" />
        <StatCard label="队列总量" value={cases.length} tone="green" />
      </div>

      <div className="two-col wide-left">
        <Section title="案件队列">
          <div className="filter-strip">
            <button className={filter === "ALL" ? "active" : ""} onClick={() => setFilter("ALL")}>全部案件</button>
            <button className={filter === "P0" ? "active" : ""} onClick={() => setFilter("P0")}>P0 优先</button>
            <button className={filter === "PENDING" ? "active" : ""} onClick={() => setFilter("PENDING")}>待审理</button>
            <button className={filter === "APPEALED" ? "active" : ""} onClick={() => setFilter("APPEALED")}>用户申诉</button>
            <button className={filter === "NEED_SUPPLEMENT" ? "active" : ""} onClick={() => setFilter("NEED_SUPPLEMENT")}>需补充</button>
            <button className={filter === "COMPLETED" ? "active" : ""} onClick={() => setFilter("COMPLETED")}>已完成</button>
          </div>
          <input className="manager-search" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索案件ID、用户、交易号、对象或申诉内容" />
          <div className="manager-case-table">
            <div className="head"><span>案件</span><span>用户/交易</span><span>决策</span><span>状态</span></div>
            {visibleCases.map((row) => (
              <button className={`manager-case-row ${selected?.case_id === row.case_id ? "selected" : ""}`} key={row.case_id} onClick={() => openCase(row)}>
                <span>{row.case_id}<small>{row.priority} · {row.alert.level}</small></span>
                <span>{row.transaction.user_id}<small>{row.transaction.transaction_id}</small></span>
                <span>{row.decision.decision}<small>风险分 {row.decision.risk_score}</small></span>
                <strong className={`badge ${row.status === "APPEALED" ? "high" : ""}`}>{statusLabel[row.status] || row.status}</strong>
              </button>
            ))}
            {!visibleCases.length && <p className="muted">没有匹配的案件。</p>}
          </div>
        </Section>

        <Section title="证据链与复核">
          {selected ? (
            <div className="case-detail">
              <div className="manager-case-head">
                <div>
                  <h3>{selected.case_id} · {selected.decision.decision}</h3>
                  <p className="muted">交易 {selected.transaction.transaction_id} · 金额 {Number(selected.transaction.amount).toLocaleString("zh-CN")}</p>
                </div>
                <strong className="badge">{statusLabel[selected.status] || selected.status}</strong>
              </div>

              <div className="detail-metrics">
                <StatCard label="风险评分" value={selected.decision.risk_score} tone="red" />
                <StatCard label="共识状态" value={selected.decision.conflict_flag ? "需仲裁" : "一致"} tone="amber" />
                <StatCard label="优先级" value={selected.priority} />
              </div>

              {selected.appeal && (
                <div className="manager-appeal-box">
                  <div>
                    <h3><MessageSquareWarning size={18} />用户申诉</h3>
                    <p>{selected.appeal.reason}</p>
                    <span>{selected.appeal.appeal_id} · {appealStatusLabel[selected.appeal.status] || selected.appeal.status}</span>
                  </div>
                  <div className="manager-materials">
                    {(selected.appeal.materials ?? []).map((item: string) => <span key={item}><FileText size={14} />{item}</span>)}
                  </div>
                </div>
              )}

              <div className="manager-transaction-box">
                <span>渠道：{selected.transaction.channel}</span>
                <span>对象：{selected.transaction.counterparty_type || "未提供"}</span>
                <span>设备：{selected.transaction.device_id || "未知"}</span>
                <span>地点：{selected.transaction.location || "未知"}</span>
              </div>

              <div className="evidence-list">
                {(evidence?.evidence_chain ?? []).map((item: any) => (
                  <article key={item.agent_id} className={item.degraded ? "evidence-degraded" : ""}>
                    <strong>{item.agent_id}</strong>
                    <span>
                      {item.risk_label} · {item.risk_score} · {item.exec_time_ms}ms
                      {item.confidence != null ? ` · 置信 ${item.confidence}` : ""}
                      {item.degraded ? " · 已降级剔除" : ""}
                    </span>
                    <p>{item.evidence?.[0]?.summary}</p>
                  </article>
                ))}
              </div>

              {(evidence?.arbitration || process?.arbitration_used) && (
                <div className="manager-arbitration-box">
                  <h3><Gavel size={18} />仲裁结论（{evidence?.arbitration?.method === "llm" ? "LLM 仲裁" : "规则仲裁"}）</h3>
                  <p>{evidence?.arbitration?.rationale ?? "该案件检测时触发了冲突仲裁，详见下方协同决策过程。"}</p>
                </div>
              )}

              {advice && (
                <div className="manager-ai-advice-box">
                  <div className="manager-ai-advice-head">
                    <h3><Sparkles size={18} />AI 审核建议 <small>LangGraph 审核助手 · {advice.llm?.model || "规则基线"} · {advice.fallback ? "规则模板兜底" : "LLM 综合"}</small></h3>
                    {advice.fallback && <span className="badge high">LLM 回退</span>}
                  </div>
                  <div className="manager-ai-advice-body">
                    <div className="manager-ai-reco">
                      <strong className={`badge ${adviceMeta[advice.advice?.recommendation]?.className || ""}`}>
                        {adviceMeta[advice.advice?.recommendation]?.label || advice.advice?.recommendation}
                      </strong>
                      <span>置信度 {(Number(advice.advice?.confidence || 0) * 100).toFixed(0)}%</span>
                    </div>
                    <p className="manager-ai-rationale">{advice.advice?.rationale}</p>
                    {(advice.candidates?.length > 0) && (
                      <div className="manager-ai-cases">
                        <h4>引用相似案例（RAG top-{advice.candidates.length}）</h4>
                        {advice.candidates.map((item: any) => (
                          <article key={item.case_id}>
                            <span><strong>{item.case_id}</strong> · {item.review_result || "未复核"} · 相似度 {Number(item.similarity).toFixed(3)}</span>
                            <small>{item.transaction_id} · {item.decision} · {Number(item.amount).toLocaleString("zh-CN")} 元</small>
                          </article>
                        ))}
                      </div>
                    )}
                    <div className="button-row">
                      <button className={adviceMeta[advice.advice?.recommendation]?.className === "reco-danger" ? "danger" : ""}
                        onClick={() => submit(adviceToResult[advice.advice?.recommendation] || "误报")}>
                        <Sparkles size={16} />按建议处理（{adviceMeta[advice.advice?.recommendation]?.label || advice.advice?.recommendation}）
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {process?.stages && (
                <div className="manager-process-box">
                  <h3>协同决策过程</h3>
                  <DecisionTimeline collaboration={process.stages} />
                </div>
              )}

              {selected.appeal && (
                <div className="client-timeline manager-timeline">
                  {(selected.appeal.timeline ?? []).map((item: any, index: number) => (
                    <article className="done" key={`${item.title}-${index}`}><span /> <div><strong>{item.title}</strong><p>{item.detail}</p></div></article>
                  ))}
                </div>
              )}

              <textarea value={remark} onChange={(event) => setRemark(event.target.value)} />
              <div className="button-row">
                <button className="danger" onClick={() => submit("欺诈")}><ShieldCheck size={16} />确认欺诈 / 驳回申诉</button>
                <button onClick={() => submit("误报")}>标记误报 / 申诉通过</button>
                <button className="client-secondary-button" onClick={() => submit("需补充")}>要求补充材料</button>
              </div>
            </div>
          ) : (
            <p className="muted">选择一个案件查看证据链。</p>
          )}
        </Section>
      </div>
    </div>
  );
}
