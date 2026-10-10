const API_PREFIX = "/api/v1";
const MANAGER_TOKEN = "demo-admin-token";
const CLIENT_TOKEN = "demo-client-token";
export const DEMO_CONFIRM_TOKEN = "demo-confirm";

export type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
  trace_id: string;
  timestamp: string;
};

function demoToken() {
  return window.location.pathname.startsWith("/client") ? CLIENT_TOKEN : MANAGER_TOKEN;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${demoToken()}`,
      ...(init?.headers || {})
    },
    ...init
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const body = (await response.json()) as ApiEnvelope<T>;
  return body.data;
}

export const api = {
  metrics: () => request<any>("/dashboard/metrics"),
  alerts: () => request<any[]>("/alerts"),
  cases: () => request<any[]>("/cases"),
  evidence: (caseId: string) => request<any>(`/cases/${caseId}/evidence`),
  reviewCase: (payload: any) => request<any>("/cases/review", { method: "POST", body: JSON.stringify(payload) }),
  appealableTransactions: (userId = "U2002") =>
    request<any[]>(`/cases/appealable-transactions?user_id=${encodeURIComponent(userId)}&limit=80`),
  submitAppeal: (payload: any) => request<any>("/cases/appeals", { method: "POST", body: JSON.stringify(payload) }),
  riskItems: () => request<any[]>("/risklist"),
  checkRisk: (value: string) => request<any>(`/risklist/check?value=${encodeURIComponent(value)}`),
  strategy: () => request<any>("/strategies/active"),
  llmStatus: () => request<any>("/strategies/llm/status"),
  validateStrategy: (payload: any) =>
    request<any>("/strategies/validate", { method: "POST", body: JSON.stringify(payload) }),
  publishStrategy: (payload: any) =>
    request<any>("/strategies/publish", { method: "POST", body: JSON.stringify(payload) }),
  learning: () => request<any>("/strategies/learning"),
  adoptLearned: (confirmToken: string) =>
    request<any>("/strategies/adopt-learned", { method: "POST", body: JSON.stringify({ confirm_token: confirmToken }) }),
  auditLogs: () => request<any[]>("/audit/logs?page_size=12"),
  detect: (transaction: any) =>
    request<any>("/detect/transaction", { method: "POST", body: JSON.stringify({ transaction }) }),
  transactions: (keyword = "") =>
    request<any[]>(`/detect/transactions?limit=80${keyword ? `&keyword=${encodeURIComponent(keyword)}` : ""}`),
  decisionProcess: (transactionId: string) =>
    request<any | null>(`/detect/decisions/${encodeURIComponent(transactionId)}/process`),
  securityCheck: (payload: any) =>
    request<any>("/security/check", { method: "POST", body: JSON.stringify(payload) }),
  reviewAdvice: (caseId: string) =>
    request<any>("/review-assistant/advice", { method: "POST", body: JSON.stringify({ case_id: caseId }) }),
  reviewCasesSearch: (query: string, topK = 3) =>
    request<any>(`/review-assistant/cases/search?q=${encodeURIComponent(query)}&top_k=${topK}`),
  auditExportUrl: () => `${API_PREFIX}/audit/logs/export`
};

export async function downloadAuditReport() {
  const response = await fetch(api.auditExportUrl(), {
    headers: { Authorization: `Bearer ${MANAGER_TOKEN}` }
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "huiyan-audit-logs.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
