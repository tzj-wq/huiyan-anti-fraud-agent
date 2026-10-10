import { BarChart3, Bell, ChevronRight, CreditCard, Database, FileSearch, Gavel, Home, Shield, Siren, SlidersHorizontal } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const managerItems = [
  { to: "/manager", label: "实时看板", icon: BarChart3 },
  { to: "/manager/cases", label: "案件审理", icon: Gavel },
  { to: "/manager/strategy", label: "策略配置", icon: SlidersHorizontal },
  { to: "/manager/data", label: "基础数据", icon: Database }
];

const clientItems = [
  { to: "/client", label: "首页", icon: Home },
  { to: "/client/security", label: "安全中心", icon: Shield },
  { to: "/client/transaction", label: "交易评估", icon: CreditCard },
  { to: "/client/report", label: "举报查询", icon: FileSearch },
  { to: "/client/appeals", label: "申诉处理", icon: Siren }
];

function ManagerShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">慧</div>
          <div>
            <strong>慧眼识诈</strong>
            <span>管理端</span>
          </div>
        </div>
        <nav>
          {managerItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink key={item.to} to={item.to} end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <main className="main manager-main">
        <Outlet />
      </main>
    </div>
  );
}

function ClientShell() {
  return (
    <div className="client-shell">
      <header className="client-topbar">
        <NavLink className="client-logo" to="/client">
          <div className="client-logo-mark">慧</div>
          <div>
            <strong>慧眼识诈</strong>
            <span>C端用户版</span>
          </div>
        </NavLink>
        <nav className="client-nav">
          {clientItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink key={item.to} to={item.to} end className={({ isActive }) => `client-nav-item ${isActive ? "active" : ""}`}>
                <Icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
        <button className="client-icon-button" type="button" aria-label="消息提醒">
          <Bell size={18} />
        </button>
      </header>
      <main className="client-main">
        <Outlet />
      </main>
      <footer className="client-footer">
        <span>账户安全托管中</span>
        <ChevronRight size={16} />
      </footer>
    </div>
  );
}

export function AppShell({ mode }: { mode: "manager" | "client" }) {
  return mode === "manager" ? <ManagerShell /> : <ClientShell />;
}
