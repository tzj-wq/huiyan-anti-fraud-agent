# 慧眼识诈 · 多 Agent 反欺诈决策引擎

金融交易反欺诈系统：用 LangGraph 编排 6 个 Agent（5 规则 + 1 LLM 语义）协同决策，配套 RAG 案例库驱动的审核助手、复核反馈驱动的权重自学习，带管理端/用户端和离线量化评估。可离线运行，不依赖外部服务。

## 启动

```powershell
.\start.ps1        # 并行启动后端(8000) + 前端(5173)，首次自动装依赖
.\smoke.ps1        # 冒烟：health / 检测 / 审核建议
```

或者手动：

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
```

管理端 `http://127.0.0.1:5173/manager`，用户端 `/client`。默认 sqlite，启动自动建表并灌演示数据（含已复核案例，RAG 开箱可检索）。要接 LLM 就在根目录配 `.env`，见文末。

## 架构

```mermaid
flowchart LR
    subgraph 前端
        M[管理端 React] --- C[用户端 React]
    end
    subgraph 后端 FastAPI · LangGraph
        D[detection 检测管线<br/>LangGraph StateGraph] --> S1[6 Agent 并行<br/>规则×5 + LLM 语义×1]
        S1 --> CA[冲突分析<br/>离群/边界/降级]
        CA -->|有分歧| ARB[仲裁<br/>规则 / LLM-as-Judge]
        CA -->|一致| F[置信度加权融合<br/>降级剔除]
        ARB --> F
        F --> DEC[PASS / REVIEW / BLOCK]
        DEC --> AL[告警 + 案件]
        AL --> RV[人工复核<br/>审核助手]
        RV --> FB[反馈信号]
        FB --> LW[权重学习<br/>EWMA + 收缩 + softmax]
        LW -->|管理员采纳| ST[策略发布]
        ST --> S1
        RV --> RAG[(RAG 案例库)]
        RAG -->|top-3 相似案例| RV
    end
    M --> D
    C --> D
```

## 核心设计

- **6-Agent 协同**。5 个规则 Agent（名单/交易/行为/设备/图关联）+ 1 个 LLM 语义 Agent（解析申诉理由、备注、聊天记录这类非结构化线索），并行独立评估，各自带特征覆盖度置信度。先做冲突分析（离群归因/阈值边界/降级检测），有分歧才触发仲裁，最后按“策略权重 × 置信度”加权融合，降级 Agent 直接剔除不参与打分。
- **仲裁双模，规则是安全基线**。默认规则仲裁，毫秒级；配了 LLM 后冲突交易交给大模型裁判（结构化 JSON、3s 预算、失败自动回退）。规则侧的降级剔除和法定人数保护，不允许被 LLM 压下去。
- **RAG 审核助手**。复核完成的案件自动进案例库（TF-IDF + 余弦，中文免分词），新案件审核时先检索 top-3 相似历史案例，LLM 结合证据链给审核建议，超时或失败回退规则模板。
- **权重自学习，人工在环**。复核结论转成每个 Agent 的正确性信号（降级的 Agent 不参与），经 EWMA 滚动准确率 + 贝叶斯收缩 + softmax 生成新权重，管理员确认后发布成新策略版本。整个流程有审计。
- **全程可解释**。每次决策的轮次、各 Agent 打分和置信度、仲裁理由、权重调整明细都存库，前端时间线展示；审核建议带引用案例。

## 效果

评估：`cd backend && python scripts/evaluate.py`，报告自动生成到 `backend/scripts/eval_report.md`。数据集 4000 笔防泄漏标注（8 个单特征 AUC 全部 ≤0.82、身份与标签独立、金额分布重叠），测试集 1200 笔。

**主对比（同一测试集）**

| 决策模式 | Precision | Recall | F1 | AUC |
|---|---|---|---|---|
| 静态加权融合（基线对照） | 0.763 | 0.993 | 0.863 | 0.983 |
| **多 Agent 协同（6 Agent）** | **0.904** | **0.960** | **0.931** | 0.983 |
| 最优单 Agent（graph-trace） | 0.957 | 0.770 | 0.853 | 0.905 |
| XGBoost | 0.949 | 0.967 | 0.958 | 0.993 |

**消融（定位每个机制的贡献）**

| 配置 | F1 | ΔF1 |
|---|---|---|
| 多 Agent 协同（全量） | 0.931 | +0.000 |
| −选择性升级（冲突一律升级） | 0.863 | -0.068 |
| −仲裁层（无升级与降权） | 0.209 | -0.722 |
| −graph-trace（leave-one-out） | 0.885 | -0.046 |

仲裁层去掉后 F1 从 0.931 掉到 0.209，说明这套冲突仲裁是召回的主要来源。

**故障注入（确定性降级 1-2 个 Agent）**

| 模式 | F1 | 误报 | 与无故障决策一致率 |
|---|---|---|---|
| 静态加权融合（降级注入 0.8 分） | 0.859 | 126 | 89.9% |
| **多 Agent 协同（降级剔除+法定人数）** | **0.896** | **44** | **92.8%** |

语义 Agent 依赖非结构化线索，合成评估集没有线索，所以离线基线里它保持降级剔除；真实 LLM 能力由线上的 LLM-as-Judge 评估验证。决策延迟平均 1.00ms，P99 1.88ms。

## LLM 增强（可选）

默认离线运行。根目录 `.env`：

```bash
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_MODEL=deepseek-chat
```

启用后：语义 Agent 开始解析非结构化线索；冲突交易走 LLM 仲裁；决策输出结构化解释；审核助手生成 RAG 引用的审核建议（8s 预算）。没配置或调用失败，自动回退本地模式，检测、告警、复核、学习闭环都不受影响。

LLM-as-Judge 实测（deepseek-v4-flash，120 案）：3s 预算内成功率 0%（推理模型平均延迟 8.9s），全部自动回退规则仲裁，生产链路无损；15s 预算下决策一致率 75%，但 LLM 过度保守（83/84 要求升级），冲突子集 F1 0.706 低于规则仲裁的 0.825——“安全基线不可降”这个设计拿到了实证。

## 其他

- **测试**：`cd backend && python -m pytest ../test tests/ -q`，81 项全绿；CI 见 `.github/workflows/ci.yml`
- **演示 Token**：管理员 `demo-admin-token`、运营 `demo-operator-token`、审计 `demo-auditor-token`、用户 `demo-client-token`；高风险操作二次确认 `demo-confirm`
- **代码结构**：`backend/app/modules/detection`（6 Agent + 冲突/仲裁/融合 + LangGraph 图）、`review_assistant`（RAG 案例库 + 审核图）、`strategy`（策略 + 权重学习）；前端在 `frontend/src`
- **更多文档**：设计决策与面试 Q&A 见 `docs/DESIGN_DECISIONS.md`；简历项目描述见 `docs/RESUME_PROJECT.md`

[English](README_EN.md)
