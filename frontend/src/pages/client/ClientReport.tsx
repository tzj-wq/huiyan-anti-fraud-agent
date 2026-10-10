import { Gift, Search, Siren } from "lucide-react";
import { useState } from "react";
import { api } from "../../services/api";

export function ClientReport() {
  const [value, setValue] = useState("U9009");
  const [result, setResult] = useState<any>();

  async function search() {
    setResult(await api.checkRisk(value));
  }

  return (
    <div className="client-page">
      <div className="client-title">
        <h1>举报查询中心</h1>
        <p>查询手机号、网址、银行卡号或收款账号的公开风险记录</p>
      </div>
      <section className="client-search-card">
        <Search size={24} />
        <input value={value} onChange={(event) => setValue(event.target.value)} placeholder="输入手机号、网址、银行卡号或收款账号..." />
        <button onClick={search}>查询</button>
      </section>
      {result && (
        <section className={`client-query-result ${result.hit ? "hit" : ""}`}>
          <strong>{result.hit ? "发现风险记录" : "暂未发现风险记录"}</strong>
          <span>{result.hit ? "建议核实对方身份后再继续交易。" : "仍建议保持警惕，避免离开官方渠道付款。"}</span>
        </section>
      )}
      <div className="client-grid">
        <article className="client-card"><Siren /><h3>举报可疑信息</h3><p>提交诈骗短信、网址、收款账号或聊天记录。</p></article>
        <article className="client-card"><Gift /><h3>举报奖励计划</h3><p>有效举报可获得积分与荣誉勋章。</p></article>
      </div>
    </div>
  );
}
