import {
  AlertTriangle,
  BookOpenCheck,
  CheckCircle2,
  Flame,
  LockKeyhole,
  Megaphone,
  ShieldCheck,
  Trophy
} from "lucide-react";

import { useEffect, useState } from "react";

import {
  HealthCheckResult,
  loadHealthCheck
} from "../../services/clientState";

export function ClientHome() {

  const [health, setHealth] =
      useState<HealthCheckResult | null>(() => loadHealthCheck());

  const score = health?.score ?? 92;

  const levelText = health
      ? `${health.level} · 最近体检 ${health.checkedAt}`
      : "安全状态良好，已开启关键防护";

  // 官方举报 / 安全相关网址
  const OFFICIAL_URLS = {
    freeze: "https://www.12377.cn",           // 一键冻结账户 → 中央网信办举报中心
    report: "https://www.12321.cn",           // 举报可疑交易 → 12321举报中心
    alerts: "http://cyberpolice.mps.gov.cn",  // 查看全部预警 → 网络违法犯罪举报网站（新址）
    abnormalLogin: "https://www.12377.cn",    // 异地登录预警
    suspiciousAccount: "https://www.12377.cn",// 可疑账户预警
    fakeService: "https://www.12377.cn",      // 冒充客服预警
    lesson: "https://www.12377.cn",           // 今日课程
    challenge: "https://www.12377.cn",        // 防诈挑战
    announcement: "https://www.12321.cn"      // 安全公告
  };

  const openUrl = (url: string) => {
    window.open(url, "_blank");
  };

  useEffect(() => {

    function handleUpdate(event: Event) {
      setHealth((event as CustomEvent<HealthCheckResult>).detail);
    }

    window.addEventListener(
        "huiyan-health-check-updated",
        handleUpdate
    );

    return () => {
      window.removeEventListener(
          "huiyan-health-check-updated",
          handleUpdate
      );
    };

  }, []);

  return (

      <div className="client-page">

        <section className="client-score-card">

          <div>
            <p className="client-eyebrow">
              账户安全评分
            </p>

            <h1>{score}</h1>

            <span>{levelText}</span>

            {health && (
                <p className="client-score-summary">
                  {health.summary}
                </p>
            )}
          </div>

          <div className="score-ring">
            <ShieldCheck size={48} />
          </div>

        </section>

        <section className="client-emergency">

          <div>
            <h2>紧急防御中心</h2>

            <p>
              发现异常转账、陌生设备或异地登录时，
              可立即冻结高风险操作。
            </p>
          </div>

          <div className="client-action-grid">

            <button
                className="client-danger-button"
                type="button"
                onClick={() => openUrl(OFFICIAL_URLS.freeze)}
            >
              <LockKeyhole size={18} />
              一键冻结账户
            </button>

            <button
                className="client-secondary-button"
                type="button"
                onClick={() => openUrl(OFFICIAL_URLS.report)}
            >
              <AlertTriangle size={18} />
              举报可疑交易
            </button>

          </div>

        </section>

        <section className="client-grid">

          <article className="client-card">
            <div className="client-card-icon blue">
              <CheckCircle2 size={22} />
            </div>

            <h3>MFA 身份核验</h3>

            <p>
              大额交易、异地登录、设备变更会触发二次确认。
            </p>

            <strong>已开启</strong>
          </article>

          <article className="client-card">
            <div className="client-card-icon amber">
              <Flame size={22} />
            </div>

            <h3>全域风险态势</h3>

            <p>
              近 24 小时已为你拦截 3 次潜在风险访问。
            </p>

            <strong>低风险</strong>
          </article>

          <article className="client-card">
            <div className="client-card-icon violet">
              <Trophy size={22} />
            </div>

            <h3>防诈成长值</h3>

            <p>
              完成今日挑战可提升账户保护等级和举报积分。
            </p>

            <strong>1280 分</strong>
          </article>

        </section>

        <section className="client-feed">

          <div className="client-section-title">

            <h2>最新安全预警 & 教育</h2>

            <button
                type="button"
                onClick={() => openUrl(OFFICIAL_URLS.alerts)}
            >
              查看全部
            </button>

          </div>

          <div className="client-feed-layout">

            <div className="client-feed-list">

              <article
                  onClick={() => openUrl(OFFICIAL_URLS.abnormalLogin)}
                  style={{ cursor: "pointer" }}
              >
                <span className="dot red" />

                <div>
                  <strong>
                    异地登录已触发二次核验
                  </strong>

                  <p>
                    来自哈尔滨的新登录行为
                    已被要求短信 + 人脸核验。
                  </p>
                </div>

              </article>

              <article
                  onClick={() => openUrl(OFFICIAL_URLS.suspiciousAccount)}
                  style={{ cursor: "pointer" }}
              >
                <span className="dot blue" />

                <div>
                  <strong>
                    可疑收款账户已加入观察名单
                  </strong>

                  <p>
                    系统建议复核交易对象身份后再进行转账。
                  </p>
                </div>

              </article>

              <article
                  onClick={() => openUrl(OFFICIAL_URLS.fakeService)}
                  style={{ cursor: "pointer" }}
              >
                <span className="dot amber" />

                <div>
                  <strong>
                    近期出现“冒充平台客服退款”高发案例
                  </strong>

                  <p>
                    不要向对方提供验证码、
                    屏幕共享或银行卡完整信息。
                  </p>
                </div>

              </article>

            </div>

            <div className="client-education-list">

              <article>

                <BookOpenCheck size={20} />

                <div>
                  <strong>今日 3 分钟课程</strong>

                  <span>
                  识别虚假客服与退款骗局
                </span>
                </div>

                <button
                    type="button"
                    onClick={() => openUrl(OFFICIAL_URLS.lesson)}
                >
                  开始
                </button>

              </article>

              <article>

                <Trophy size={20} />

                <div>
                  <strong>防诈挑战</strong>

                  <span>
                  完成后成长值 +20
                </span>
                </div>

                <button
                    type="button"
                    onClick={() => openUrl(OFFICIAL_URLS.challenge)}
                >
                  挑战
                </button>

              </article>

              <article>

                <Megaphone size={20} />

                <div>
                  <strong>安全公告</strong>

                  <span>
                  陌生二维码付款风险提醒
                </span>
                </div>

                <button
                    type="button"
                    onClick={() => openUrl(OFFICIAL_URLS.announcement)}
                >
                  查看
                </button>

              </article>

            </div>

          </div>

        </section>

      </div>
  );
}