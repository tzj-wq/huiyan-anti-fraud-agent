import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { Section } from "../../components/Section";
import { StatCard } from "../../components/StatCard";
import { api, downloadAuditReport } from "../../services/api";

export function ManagerData() {
  const [riskItems, setRiskItems] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [query, setQuery] = useState("U9009");
  const [check, setCheck] = useState<any>();

  useEffect(() => {
    api.riskItems().then(setRiskItems);
    api.auditLogs().then(setLogs);
  }, []);

  async function runCheck() {
    setCheck(await api.checkRisk(query));
  }

  function exportAudit() {
    downloadAuditReport();
  }

  return (
    <div className="page">
      <div className="page-title">
        <h1>基础数据管理</h1>
        <p>名单库、外部接口、知识共享池与操作审计日志</p>
      </div>
      <div className="two-col">
        <Section title="名单库分级管理">
          <div className="data-stat-row">
            <StatCard label="名单项" value={riskItems.length} />
            <StatCard label="接口在线" value="4/4" tone="green" />
          </div>
          <div className="inline-form">
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
            <button onClick={runCheck}>实时查询</button>
          </div>
          {check && <p className="notice">{check.hit ? `命中 ${check.item.risk_level}` : "未命中名单"}</p>}
          <div className="list">
            {riskItems.map((item) => (
              <div className="list-row" key={item.item_id}><span>{item.item_value}</span><strong>{item.list_type} · {item.risk_level}</strong></div>
            ))}
          </div>
        </Section>
        <Section title="操作审计日志" action={<button onClick={exportAudit}><Download size={16} /> 导出审计报告</button>}>
          <div className="list">
            {logs.map((log) => (
              <div className="list-row" key={log.log_id}>
                <span>{log.module} · {log.action}</span>
                <strong>{log.actor}</strong>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
