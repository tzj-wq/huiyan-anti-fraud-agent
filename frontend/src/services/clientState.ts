export type LoginDevice = {
  id: string;
  name: string;
  value: string;
  location: string;
  lastSeen: string;
  trusted: boolean;
};

const DEVICE_KEY = "huiyan-client-login-devices";
const HEALTH_KEY = "huiyan-client-health-check";

export const defaultLoginDevices: LoginDevice[] = [
  { id: "dev-iphone", name: "iPhone 15 Pro", value: "DEV-IPHONE-15", location: "上海", lastSeen: "刚刚", trusted: true },
  { id: "dev-windows", name: "Windows Chrome", value: "DEV-WINDOWS-PC", location: "深圳", lastSeen: "2 小时前", trusted: true },
  { id: "dev-risk", name: "陌生 Android 设备", value: "DEV-RISK-X", location: "哈尔滨", lastSeen: "昨天 23:18", trusted: false }
];

export function loadLoginDevices(): LoginDevice[] {
  try {
    const raw = localStorage.getItem(DEVICE_KEY);
    return raw ? JSON.parse(raw) : defaultLoginDevices;
  } catch {
    return defaultLoginDevices;
  }
}

export function saveLoginDevices(devices: LoginDevice[]) {
  localStorage.setItem(DEVICE_KEY, JSON.stringify(devices));
}

export type HealthCheckResult = {
  score: number;
  level: string;
  summary: string;
  recommendations?: string[];
  llm?: {
    enabled: boolean;
    model: string;
  };
  checkedAt: string;
};

export function loadHealthCheck(): HealthCheckResult | null {
  try {
    const raw = localStorage.getItem(HEALTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveHealthCheck(result: Omit<HealthCheckResult, "checkedAt">) {
  const next = { ...result, checkedAt: new Date().toLocaleString("zh-CN", { hour12: false }) };
  localStorage.setItem(HEALTH_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent("huiyan-health-check-updated", { detail: next }));
  return next;
}
