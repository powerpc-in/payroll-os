// Client-side mirror of backend RBAC (backend/lib/rbac.py) — UI gating only.
// The backend remains the enforcement point; never trust this for security.

export const ROLE_PERMISSIONS: Record<string, string[]> = {
  SUPER_ADMIN: ["*"],
  COMPANY_ADMIN: ["*"],
  HR_ADMIN: [
    "employees.view", "employees.create", "employees.edit", "employees.view_sensitive",
    "salary.view", "attendance.view", "attendance.manage",
    "leave.view", "leave.manage", "leave.approve",
    "reimbursements.view", "reimbursements.manage",
    "loans.view", "documents.view", "documents.upload", "documents.delete",
    "reports.view", "reports.export", "dashboards.view", "audit.view", "self.view",
  ],
  PAYROLL_ADMIN: [
    "employees.view", "employees.view_sensitive", "salary.view", "salary.manage",
    "payroll.view", "payroll.calculate", "payroll.review", "payroll.approve",
    "payroll.lock", "payroll.reverse",
    "tax.view", "tax.manage", "attendance.view", "leave.view",
    "reimbursements.view", "reimbursements.approve",
    "loans.view", "loans.manage",
    "reports.view", "reports.export", "reports.manage",
    "dashboards.view", "compliance.view", "audit.view", "self.view",
  ],
  FINANCE: [
    "employees.view", "payroll.view", "tax.view",
    "reports.view", "reports.export", "dashboards.view", "compliance.view",
    "audit.view", "self.view",
  ],
  MANAGER: [
    "employees.view", "attendance.view", "leave.view", "leave.approve",
    "dashboards.view", "self.view", "documents.view", "documents.upload",
  ],
  EMPLOYEE: ["self.view", "documents.view", "documents.upload", "dashboards.view",
             "leave.view", "reimbursements.view", "loans.view", "tax.view"],
};

export function can(permissions: string[] | undefined, perm: string): boolean {
  if (!permissions) return false;
  return permissions.includes("*") || permissions.includes(perm);
}
