"""Role-based access control. Roles map to granular permission strings.

The backend is the single source of truth — the frontend keeps a mirror of this
map for UI gating only, never for enforcement.
"""

ROLES = [
    "SUPER_ADMIN",
    "COMPANY_ADMIN",
    "HR_ADMIN",
    "PAYROLL_ADMIN",
    "FINANCE",
    "MANAGER",
    "EMPLOYEE",
]

_ALL = [
    "employees.view", "employees.create", "employees.edit", "employees.delete",
    "employees.view_sensitive",
    "salary.view", "salary.manage",
    "payroll.view", "payroll.calculate", "payroll.review", "payroll.approve",
    "payroll.lock", "payroll.reverse",
    "tax.view", "tax.manage",
    "attendance.view", "attendance.manage",
    "leave.view", "leave.manage", "leave.approve",
    "reimbursements.view", "reimbursements.manage", "reimbursements.approve",
    "loans.view", "loans.manage",
    "documents.view", "documents.upload", "documents.delete",
    "reports.view", "reports.export", "reports.manage",
    "dashboards.view",
    "compliance.view", "compliance.manage",
    "integrations.manage",
    "webhooks.manage",
    "settings.manage", "users.manage",
    "audit.view",
    "imports.manage",
    "self.view",
]

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "SUPER_ADMIN": {"*"},
    "COMPANY_ADMIN": set(_ALL),
    "HR_ADMIN": {
        "employees.view", "employees.create", "employees.edit", "employees.view_sensitive",
        "salary.view", "attendance.view", "attendance.manage",
        "leave.view", "leave.manage", "leave.approve",
        "reimbursements.view", "reimbursements.manage",
        "loans.view", "documents.view", "documents.upload", "documents.delete",
        "reports.view", "reports.export", "dashboards.view", "audit.view", "self.view",
    },
    "PAYROLL_ADMIN": {
        "employees.view", "employees.view_sensitive", "salary.view", "salary.manage",
        "payroll.view", "payroll.calculate", "payroll.review", "payroll.approve",
        "payroll.lock", "payroll.reverse",
        "tax.view", "tax.manage",
        "attendance.view", "leave.view",
        "reimbursements.view", "reimbursements.approve",
        "loans.view", "loans.manage",
        "reports.view", "reports.export", "reports.manage",
        "dashboards.view", "compliance.view", "audit.view", "self.view",
    },
    "FINANCE": {
        "employees.view", "payroll.view", "tax.view",
        "reports.view", "reports.export", "dashboards.view", "compliance.view",
        "audit.view", "self.view",
    },
    "MANAGER": {
        "employees.view", "attendance.view", "leave.view", "leave.approve",
        "dashboards.view", "self.view", "documents.view", "documents.upload",
    },
    "EMPLOYEE": {"self.view", "documents.view", "documents.upload", "dashboards.view",
                 "leave.view", "reimbursements.view", "loans.view", "tax.view"},
}


def has_permission(role: str, perm: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or perm in perms


def permissions_for_role(role: str) -> list[str]:
    perms = ROLE_PERMISSIONS.get(role, set())
    return sorted(perms)
