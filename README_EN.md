# Huiyan Fraud-Detection Platform · Multi-Agent Decision Engine

A transaction fraud-detection system: 6 agents (5 rule + 1 LLM semantic) orchestrated with LangGraph, plus a RAG-driven review assistant, review-feedback weight learning, manager/client UIs and an offline evaluation suite. Runs fully offline, no external services required.

## Run

```powershell
.\start.ps1        # backend(8000) + frontend(5173) in parallel; installs deps on first run
.\smoke.ps1        # smoke: health / detect / review advice
```

Or manually:

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
```

Manager UI at `http://127.0.0.1:5173/manager`, client UI at `/client`. Uses sqlite by default; the DB is created and seeded with demo data on startup (including reviewed cases, so the RAG base works out of the box). To enable LLM, configure `.env` in the project root, see below.

## Architecture

```mermaid
flowchart LR
    subgraph Frontend
        M[Manager React] --- C[Client React]
    end
    subgraph Backend FastAPI · LangGraph
        D[detection pipeline<br/>LangGraph StateGraph] --> S1[6 agents in parallel<br/>rule x5 + LLM semantic x1]
        S1 --> CA[Conflict analysis<br/>outlier / boundary / degraded]
        CA -->|conflict| ARB[Arbitration<br/>rule / LLM-as-Judge]
        CA -->|consistent| F[Confidence-weighted fusion<br/>degraded excluded]
        ARB --> F
        F --> DEC[PASS / REVIEW / BLOCK]
        DEC --> AL[Alert + Case]
        AL --> RV[Human review<br/>assistant]
        RV --> FB[Feedback]
        FB --> LW[Weight learning<br/>EWMA + shrinkage + softmax]
        LW -->|admin adopt| ST[Strategy release]
        ST --> S1
        RV --> RAG[(RAG case base)]
        RAG -->|top-3 similar| RV
    end
    M --> D
    C --> D
```

## Core design

- **6-agent collaboration**. 5 rule agents (list / transaction / behavior / device / graph) + 1 LLM semantic agent (parses appeal reasons, remarks, chat records), evaluating in parallel with per-agent confidence from feature coverage. Conflict analysis (outlier attribution / boundary / degradation) triggers arbitration only when needed; the final decision is a confidence-weighted fusion where degraded agents are excluded.
- **Dual-mode arbitration, rules are the safety baseline**. Rule arbitration by default (sub-millisecond); with an LLM configured, conflict transactions go to the LLM judge (strict JSON, 3s budget, fallback on failure). Degradation exclusion and quorum protection can never be downgraded by the LLM.
- **RAG review assistant**. Reviewed cases are indexed automatically (TF-IDF + cosine, no Chinese tokenizer needed); new reviews first retrieve top-3 similar historical cases, then the LLM gives a recommendation, falling back to rule templates on timeout or failure.
- **Online weight learning with human in the loop**. Review verdicts become per-agent correctness signals (degraded agents skipped), transformed through EWMA rolling accuracy + Bayesian shrinkage + softmax into new weights, which are published as a new strategy version after admin confirmation. Fully audited.
- **End-to-end explainability**. Rounds, per-agent scores/confidences, arbitration rationale and weight adjustments are persisted and shown as a timeline in the UI; review advice cites its evidence cases.

## Results

Run `cd backend && python scripts/evaluate.py` (report → `backend/scripts/eval_report.md`). Dataset: 4,000 leakage-audited labeled transactions (all 8 single-feature AUCs ≤ 0.82, identity independent of label, overlapping amount distributions); 1,200-test split.

**Main comparison (same test set)**

| Decision mode | Precision | Recall | F1 | AUC |
|---|---|---|---|---|
| Static weighted fusion (baseline) | 0.763 | 0.993 | 0.863 | 0.983 |
| **Multi-agent collaboration (6 agents)** | **0.904** | **0.960** | **0.931** | 0.983 |
| Best single agent (graph-trace) | 0.957 | 0.770 | 0.853 | 0.905 |
| XGBoost | 0.949 | 0.967 | 0.958 | 0.993 |

**Ablation (mechanism attribution)**

| Config | F1 | ΔF1 |
|---|---|---|
| Multi-agent collaboration (full) | 0.931 | +0.000 |
| −selective escalation (escalate all) | 0.863 | -0.068 |
| −arbitration layer (no escalation/demotion) | 0.209 | -0.722 |
| −graph-trace (leave-one-out) | 0.885 | -0.046 |

Removing the arbitration layer drops F1 from 0.931 to 0.209 — conflict arbitration is the main source of recall.

**Fault injection (deterministically degrade 1-2 agents)**

| Mode | F1 | FP | Agreement with no-fault decisions |
|---|---|---|---|
| Static weighted fusion (degraded injected 0.8) | 0.859 | 126 | 89.9% |
| **Multi-agent collaboration (exclusion + quorum)** | **0.896** | **44** | **92.8%** |

The semantic agent depends on unstructured clues; the synthetic eval set has none, so it stays degraded-excluded offline; its real LLM capability is covered by the online LLM-as-Judge evaluation. Decision latency: mean 1.00 ms, P99 1.88 ms.

## LLM enhancement (optional)

Offline by default. Create `.env` in the project root:

```bash
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_MODEL=deepseek-chat
```

When enabled: the semantic agent parses unstructured clues, conflict transactions use LLM arbitration, decisions get structured explanations, and the review assistant produces RAG-cited advice (8s budget). If unconfigured or failing, everything falls back to the local mode; detection, alerts, review and the learning loop are unaffected.

Measured with deepseek-v4-flash on 120 cases: 0% success within the production 3s budget (reasoning model, mean latency 8.9s) — all timeouts auto-fall back to rule arbitration; at a 15s budget, 75% decision agreement but the LLM over-escalates (83/84 requests escalation), conflict-subset F1 0.706 below rule arbitration 0.825 — empirical support for the "safety baseline not downgradable" design.

## Misc

- **Tests**: `cd backend && python -m pytest ../test tests/ -q` — 81 passing; CI in `.github/workflows/ci.yml`
- **Demo tokens**: admin `demo-admin-token`, operator `demo-operator-token`, auditor `demo-auditor-token`, client `demo-client-token`; high-risk ops need `demo-confirm`
- **Code layout**: `backend/app/modules/detection` (6 agents + conflict/arbitration/fusion + LangGraph graph), `review_assistant` (RAG + review graph), `strategy` (config + weight learning); frontend in `frontend/src`
- **More docs**: design decisions & interview Q&A in `docs/DESIGN_DECISIONS.md`; resume project description in `docs/RESUME_PROJECT.md`

[中文](README.md)
