# 简历项目描述：慧眼（Huiyan）—— LangGraph 多 Agent 反欺诈决策引擎

> 可直接写进简历"项目经历"栏。所有数字来自项目自带离线评估（`backend/scripts/eval_report.md`，1200 笔防泄漏测试集）与真实 LLM 实测，可演示、可复现（README + 一键启动 + 81 项测试）。

## 复制即用版（精简 · 突出设计亮点，2026.10 更新）

**慧眼（Huiyan）多 Agent 反欺诈决策引擎**｜独立开发｜2026.03 – 2026.09
技术栈：Python · FastAPI · LangGraph · scikit-learn · DeepSeek API · React/TypeScript

- **多 Agent 协同决策（LangGraph 编排）**：6-Agent（5 规则 + 1 LLM 语义）并行评估 → 冲突归因 → 条件路由仲裁（arbitrate/skip）→ 置信度加权融合；1200 笔防泄漏测试集 **F1 0.931**（vs 单 Agent 0.853）；消融实证仲裁层是召回引擎——移除后 F1 跌至 0.209
- **LLM 增强不失控（混合决策设计）**：双模仲裁"规则安全基线 + LLM-as-Judge（只升不降）"；LLM 分档超时 3.5/3/8s，degraded 剔除 + 规则兜底；故障注入下 **F1 0.896、决策一致率 92.8%**
- **数据飞轮（RAG + 在线学习）**：复核结论沉淀 RAG 案例库（TF-IDF 检索 <1ms）并驱动 Agent 权重在线学习（EWMA + 贝叶斯收缩 + softmax），人工确认后发布——系统越用越准

工程：推理延迟 1.00ms（P99 1.88ms）· 81 项测试 + CI · LLM-as-Judge 120 案实测（负面结果如实上报）· 管理端可视化证据链与 AI 审核面板

**一句话版**：LangGraph 编排的多 Agent 反欺诈决策系统：6-Agent 协同 + 双模仲裁 + RAG 案例库 + LLM 审核助手 + 权重在线学习，评估/消融/故障注入全实证，可一键启动演示。

## 项目概述（一段话）

**慧眼（Huiyan）反欺诈决策引擎**｜Python/FastAPI + LangGraph + React/TypeScript｜个人独立开发
设计并实现了一套 **LangGraph 显式图编排的 6-Agent 混合协同反欺诈决策引擎**（5 个规则 Agent + 1 个 LLM 语义 Agent）：并行独立评估 → 冲突归因 → 双模仲裁（规则/LLM-as-Judge，条件路由）→ 置信度加权融合；配套 **RAG 案例库驱动的 LLM 人工审核助手**（TF-IDF 余弦检索 top-3 相似案例 + 审核建议自动生成、超时回退规则模板）与**复核反馈驱动的 Agent 权重在线学习闭环**（EWMA + 贝叶斯收缩 + softmax）。在 1200 笔防泄漏测试集上，协同决策 F1 0.931（precision 0.904 / recall 0.960 / AUC 0.983），显著优于最优单 Agent 0.853；故障注入下 F1 保持 0.896、决策一致率 92.8%；推理延迟 1.00ms（P99 1.88ms）。管理端 React 可视化完整呈现 6-Agent 证据链、仲裁轨迹与 AI 审核建议。

## 量化亮点（4 bullets）

- **多 Agent 协同决策引擎**：基于 LangGraph StateGraph 编排 6-Agent（行为建模/设备指纹/图关联/名单匹配/交易分析规则 Agent + DeepSeek 语义分析 Agent）并行评估与条件路由仲裁；在 1200 笔防泄漏测试集上 F1 0.931（precision 0.904 / recall 0.960 / AUC 0.983），优于最优单 Agent 0.853；消融实验证明仲裁层是召回引擎——移除后 F1 崩塌至 0.209。
- **RAG 案例库 + LLM 人工审核助手**：复核完成的案件自动沉淀为检索文档（TF-IDF char 2-3gram 中文免分词 + 余弦相似度，<1ms），新案件由 LangGraph 审核图（read_case → RAG retrieve → LLM advise）检索 top-3 相似案例并生成结构化审核建议（REVIEW_CONFIRM/RELEASE/ESCALATE + 置信度 + 理由）；8s 预算下真实 DeepSeek 建议约 2/3 命中，超时自动回退规则模板；LLM 建议必须人工确认才落地，复核结论回流案例库与学习信号，形成数据飞轮。
- **权重在线学习闭环**：复核反馈驱动 6-Agent 权重在线学习（EWMA 滚动准确率 + 贝叶斯收缩防小样本过拟合 + softmax 温和映射）；LLM 语义 Agent 超时降级时剔除而非注入保守分，且不污染冲突判定与学习信号；学习权重需管理员对比后二次确认采纳发布（审计留痕）。
- **工程化与实证**：双模仲裁安全基线设计经 120 案真实 LLM 实测（3s 预算回退率 100% → 规则基线无损、15s 预算一致率 75%，LLM 过度保守的负面结果如实上报）；故障注入下协同 F1 0.896 / 决策一致率 92.8% / 仅 44 误报（vs 静态 126）；推理延迟 1.00ms（P99 1.88ms）；81 项测试全绿 + GitHub Actions CI 三阶段（后端/前端/评估）。

## 技术栈

Python 3.11 · FastAPI · LangGraph · scikit-learn（TF-IDF）· DeepSeek API · SQLite/SQLAlchemy · React 18 + TypeScript + Vite · ECharts · pytest · GitHub Actions

## 一句话亮点（面试开场）

> "一个把'多 Agent 编排、LLM 与规则混合决策、RAG、在线学习、可观测审计'串成完整闭环的反欺诈系统——评估、消融、故障注入、LLM 实测都有真实数字，能一键启动演示。"

## 建议的展开顺序（1 分钟介绍）

1. 为什么做：构建一套"可解释、可降级、可学习"的风控决策系统（30s）
2. 怎么做的：LangGraph 双图（检测图 + 审核图）→ 6-Agent → 双模仲裁 → RAG 审核助手 → 学习闭环（30s）
3. 怎么证明：评估表 + 消融 + 故障注入 + LLM 实测 + 81 测试 + 一键演示（30s）
