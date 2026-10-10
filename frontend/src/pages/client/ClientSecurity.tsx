import { ArrowDown, ArrowUp, Fingerprint, KeyRound, Lock, MonitorSmartphone, ShieldCheck, Smartphone, Trash2, UserCheck, Wifi } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../services/api";
import { loadLoginDevices, saveHealthCheck, saveLoginDevices } from "../../services/clientState";

type SecurityTab = "core" | "devices" | "mfa" | "privacy";

export function ClientSecurity() {
  const [tab, setTab] = useState<SecurityTab>("core");
  const [smsEnabled, setSmsEnabled] = useState(true);
  const [faceEnabled, setFaceEnabled] = useState(true);
  const [largeTransferCheck, setLargeTransferCheck] = useState(true);
  const [mfaOrder, setMfaOrder] = useState(["短信动态码", "人脸核验", "网络环境挑战"]);
  const [devices, setDevices] = useState(loadLoginDevices);
  const [privacyItems, setPrivacyItems] = useState([
    { id: "pay", name: "支付画像授权", scope: "交易风控与异常识别", weak: false },
    { id: "marketing", name: "营销偏好授权", scope: "活动推荐与券包提醒", weak: true },
    { id: "location", name: "常用地授权", scope: "异地登录风险判断", weak: false }
  ]);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<any>();

  const riskDeviceCount = useMemo(() => devices.filter((item) => !item.trusted).length, [devices]);

  useEffect(() => {
    saveLoginDevices(devices);
  }, [devices]);

  function removeDevice(id: string) {
    setDevices((items) => items.filter((item) => item.id !== id));
  }

  function clearWeakPrivacy() {
    setPrivacyItems((items) => items.filter((item) => !item.weak));
  }

  function trustDevice(id: string) {
    setDevices((items) => items.map((item) => item.id === id ? { ...item, trusted: true, lastSeen: "刚刚" } : item));
  }

  function moveMfa(index: number, direction: -1 | 1) {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= mfaOrder.length) return;
    setMfaOrder((items) => {
      const next = [...items];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  }

  async function runSecurityCheck() {
    setChecking(true);
    const result = await api.securityCheck({
      devices,
      mfa: { sms_enabled: smsEnabled, face_enabled: faceEnabled, network_challenge: true },
      privacy_items: privacyItems,
      recent_logs: [
        { action: "修改支付密码", result: "本人确认" },
        { action: "新增可信设备", result: "已核验" },
        { action: "异地登录挑战", result: "已拦截" }
      ]
    });
    const saved = saveHealthCheck(result);
    setCheckResult(saved);
    setChecking(false);
  }

  return (
    <div className="client-page">
      <div className="client-title">
        <div>
          <h1>安全中心</h1>
          <p>管理核心防护、登录设备、MFA 核验与隐私授权。</p>
        </div>
        <button type="button" onClick={runSecurityCheck}>{checking ? "体检中..." : "安全体检"}</button>
      </div>
      {checkResult && (
        <section className="client-health-result">
          <div>
            <strong>{checkResult.score}</strong>
            <span>{checkResult.level} · {checkResult.llm?.enabled ? "LLM 已参与评估" : "本地回退评估"}</span>
          </div>
          <p>{checkResult.summary}</p>
          <ul>
            {(checkResult.recommendations ?? []).map((item: string) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      )}
      <div className="client-security-layout">
        <aside className="client-tab-list">
          <button className={tab === "core" ? "active" : ""} onClick={() => setTab("core")}><ShieldCheck size={18} />核心防护</button>
          <button className={tab === "devices" ? "active" : ""} onClick={() => setTab("devices")}><MonitorSmartphone size={18} />登录设备</button>
          <button className={tab === "mfa" ? "active" : ""} onClick={() => setTab("mfa")}><KeyRound size={18} />MFA 核验</button>
          <button className={tab === "privacy" ? "active" : ""} onClick={() => setTab("privacy")}><UserCheck size={18} />隐私授权</button>
        </aside>

        {tab === "core" && (
          <section className="client-panel">
            <div className="client-panel-head">
              <div>
                <h2>核心防护总览</h2>
                <p>账户、设备、交易和敏感操作的实时保护状态</p>
              </div>
              <span className="client-status">防护中</span>
            </div>
            <div className="client-protection-grid">
              <article><ShieldCheck /><strong>登录保护</strong><span>已开启</span></article>
              <article><Fingerprint /><strong>设备指纹</strong><span>可信设备 {devices.length - riskDeviceCount} 台</span></article>
              <article><KeyRound /><strong>交易二次确认</strong><span>{largeTransferCheck ? "大额必验" : "仅异常触发"}</span></article>
            </div>
            <label className="client-switch-card">
              <div>
                <strong>大额交易二次核验</strong>
                <span>关闭后，仅在设备、地点或对象异常时触发强校验。</span>
              </div>
              <input type="checkbox" checked={largeTransferCheck} onChange={(event) => setLargeTransferCheck(event.target.checked)} />
            </label>
            <div className="client-table">
              <div><span>修改支付密码</span><strong>本人确认</strong><em>2026-05-27 09:12</em></div>
              <div><span>新增可信设备</span><strong>已核验</strong><em>2026-05-26 21:40</em></div>
              <div><span>异地登录挑战</span><strong>已拦截</strong><em>2026-05-26 08:22</em></div>
            </div>
          </section>
        )}

        {tab === "devices" && (
          <section className="client-panel">
            <div className="client-panel-head">
              <div>
                <h2>登录设备管理</h2>
                <p>移除不认识的设备后，该设备再次登录将触发强 MFA。</p>
              </div>
              <span className={riskDeviceCount ? "client-status warning" : "client-status"}>{riskDeviceCount ? `${riskDeviceCount} 台异常` : "全部可信"}</span>
            </div>
            <div className="client-device-list">
              {devices.map((device) => (
                <article key={device.id} className={!device.trusted ? "risk" : ""}>
                  <div className="client-device-icon"><Smartphone size={22} /></div>
                  <div>
                    <strong>{device.name}</strong>
                    <span>{device.location} · {device.lastSeen}</span>
                  </div>
                  <em>{device.trusted ? "可信设备" : "待核验"}</em>
                  <div className="client-device-actions">
                    {!device.trusted && <button className="client-secondary-button" onClick={() => trustDevice(device.id)}>设为可信</button>}
                    <button className="client-ghost-button" onClick={() => removeDevice(device.id)}><Trash2 size={16} />移除</button>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {tab === "mfa" && (
          <section className="client-panel">
            <div className="client-panel-head">
              <div>
                <h2>MFA 认证编排</h2>
                <p>配置短信、人脸、设备指纹等多因素认证方式。</p>
              </div>
              <span className="client-status">推荐配置</span>
            </div>
            <div className="client-mfa-list">
              <label>
                <div><KeyRound /><strong>短信动态码</strong><span>登录与转账默认开启</span></div>
                <input type="checkbox" checked={smsEnabled} onChange={(event) => setSmsEnabled(event.target.checked)} />
              </label>
              <label>
                <div><Fingerprint /><strong>人脸核验</strong><span>大额交易、申诉解封强制核验</span></div>
                <input type="checkbox" checked={faceEnabled} onChange={(event) => setFaceEnabled(event.target.checked)} />
              </label>
              <label>
                <div><Wifi /><strong>网络环境挑战</strong><span>公共 Wi-Fi 与代理网络触发风险挑战</span></div>
                <input type="checkbox" checked readOnly />
              </label>
            </div>
            <div className="client-mfa-order">
              <h3>MFA 编排顺序</h3>
              {mfaOrder.map((item, index) => (
                <div key={item}>
                  <span>{index + 1}</span>
                  <strong>{item}</strong>
                  <button className="client-secondary-button" onClick={() => moveMfa(index, -1)} disabled={index === 0}><ArrowUp size={14} /></button>
                  <button className="client-secondary-button" onClick={() => moveMfa(index, 1)} disabled={index === mfaOrder.length - 1}><ArrowDown size={14} /></button>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === "privacy" && (
          <section className="client-panel">
            <div className="client-panel-head">
              <div>
                <h2>授权与隐私控制</h2>
                <p>清理弱授权，查看风控使用的数据范围。</p>
              </div>
              <button className="client-secondary-button" onClick={clearWeakPrivacy}>一键清空弱授权</button>
            </div>
            <div className="client-privacy-list">
              {privacyItems.map((item) => (
                <article key={item.id}>
                  <div><Lock size={18} /><strong>{item.name}</strong></div>
                  <span>{item.scope}</span>
                  <em>{item.weak ? "弱授权" : "必要授权"}</em>
                </article>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
