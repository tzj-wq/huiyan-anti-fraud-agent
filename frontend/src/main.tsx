import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ClientAppeals } from "./pages/client/ClientAppeals";
import { ClientHome } from "./pages/client/ClientHome";
import { ClientReport } from "./pages/client/ClientReport";
import { ClientSecurity } from "./pages/client/ClientSecurity";
import { ClientTransaction } from "./pages/client/ClientTransaction";
import { ManagerCases } from "./pages/manager/ManagerCases";
import { ManagerDashboard } from "./pages/manager/ManagerDashboard";
import { ManagerData } from "./pages/manager/ManagerData";
import { ManagerStrategy } from "./pages/manager/ManagerStrategy";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Router>
      <Routes>
        <Route path="/" element={<Navigate to="/manager" replace />} />
        <Route element={<AppShell mode="manager" />}>
          <Route path="/manager" element={<ManagerDashboard />} />
          <Route path="/manager/cases" element={<ManagerCases />} />
          <Route path="/manager/strategy" element={<ManagerStrategy />} />
          <Route path="/manager/data" element={<ManagerData />} />
        </Route>
        <Route element={<AppShell mode="client" />}>
          <Route path="/client" element={<ClientHome />} />
          <Route path="/client/security" element={<ClientSecurity />} />
          <Route path="/client/transaction" element={<ClientTransaction />} />
          <Route path="/client/report" element={<ClientReport />} />
          <Route path="/client/appeals" element={<ClientAppeals />} />
        </Route>
      </Routes>
    </Router>
  </React.StrictMode>
);
