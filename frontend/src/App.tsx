import { Routes, Route, Navigate } from "react-router-dom";
import AppShell, { RequireAuth } from "@/components/layout/AppShell";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import Onboarding from "@/pages/Onboarding";
import Dashboard from "@/pages/Dashboard";
import Employees from "@/pages/Employees";
import EmployeeDetail from "@/pages/EmployeeDetail";
import Salary from "@/pages/Salary";
import Attendance from "@/pages/Attendance";
import Leave from "@/pages/Leave";
import Reimbursements from "@/pages/Reimbursements";
import Loans from "@/pages/Loans";
import Payroll from "@/pages/Payroll";
import PayrollRun from "@/pages/PayrollRun";
import Reports from "@/pages/Reports";
import Compliance from "@/pages/Compliance";
import Integrations from "@/pages/Integrations";
import Webhooks from "@/pages/Webhooks";
import Audit from "@/pages/Audit";
import Imports from "@/pages/Imports";
import Settings from "@/pages/Settings";
import Notifications from "@/pages/Notifications";
import SelfService from "@/pages/SelfService";
import NotFound from "@/pages/NotFound";
import { Toaster } from "@/components/ui/sonner";

// One <Route> per page in src/pages; BrowserRouter already wraps this in main.tsx.
export default function App() {
  return (
    <>
      <Toaster richColors position="bottom-right" />
      <Routes>
      <Route path="/" element={<Navigate to="/app" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
      <Route path="/app" element={<RequireAuth><AppShell><Dashboard /></AppShell></RequireAuth>} />
      <Route path="/app/employees" element={<RequireAuth><AppShell><Employees /></AppShell></RequireAuth>} />
      <Route path="/app/employees/:id" element={<RequireAuth><AppShell><EmployeeDetail /></AppShell></RequireAuth>} />
      <Route path="/app/salary" element={<RequireAuth><AppShell><Salary /></AppShell></RequireAuth>} />
      <Route path="/app/attendance" element={<RequireAuth><AppShell><Attendance /></AppShell></RequireAuth>} />
      <Route path="/app/leave" element={<RequireAuth><AppShell><Leave /></AppShell></RequireAuth>} />
      <Route path="/app/reimbursements" element={<RequireAuth><AppShell><Reimbursements /></AppShell></RequireAuth>} />
      <Route path="/app/loans" element={<RequireAuth><AppShell><Loans /></AppShell></RequireAuth>} />
      <Route path="/app/payroll" element={<RequireAuth><AppShell><Payroll /></AppShell></RequireAuth>} />
      <Route path="/app/payroll/:id" element={<RequireAuth><AppShell><PayrollRun /></AppShell></RequireAuth>} />
      <Route path="/app/reports" element={<RequireAuth><AppShell><Reports /></AppShell></RequireAuth>} />
      <Route path="/app/compliance" element={<RequireAuth><AppShell><Compliance /></AppShell></RequireAuth>} />
      <Route path="/app/integrations" element={<RequireAuth><AppShell><Integrations /></AppShell></RequireAuth>} />
      <Route path="/app/webhooks" element={<RequireAuth><AppShell><Webhooks /></AppShell></RequireAuth>} />
      <Route path="/app/audit" element={<RequireAuth><AppShell><Audit /></AppShell></RequireAuth>} />
      <Route path="/app/imports" element={<RequireAuth><AppShell><Imports /></AppShell></RequireAuth>} />
      <Route path="/app/settings" element={<RequireAuth><AppShell><Settings /></AppShell></RequireAuth>} />
      <Route path="/app/notifications" element={<RequireAuth><AppShell><Notifications /></AppShell></RequireAuth>} />
      <Route path="/me" element={<RequireAuth><AppShell><SelfService /></AppShell></RequireAuth>} />
      <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
