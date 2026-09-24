"""Regression tests for tax, manager-team, salary-field, and tenant authorization."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from lib.auth import Context
from routers import attendance, employees, leave, reports, tax
from lib import team_scope
from services import tax_year_profiles


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *args):
        return self

    def skip(self, n):
        self.docs = self.docs[n:]
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n):
        return deepcopy(self.docs[:n])


def matches(doc, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(doc, branch) for branch in expected):
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if doc.get(key) not in expected["$in"]:
                return False
        elif isinstance(expected, dict) and "$regex" in expected:
            if expected["$regex"].lower() not in str(doc.get(key, "")).lower():
                return False
        elif doc.get(key) != expected:
            return False
    return True


class Collection:
    def __init__(self, docs=()):
        self.docs = deepcopy(list(docs))

    async def find_one(self, query, projection=None):
        doc = next((d for d in self.docs if matches(d, query)), None)
        return deepcopy(doc)

    def find(self, query, projection=None):
        return Cursor([d for d in self.docs if matches(d, query)])

    async def count_documents(self, query):
        return sum(matches(d, query) for d in self.docs)

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))

    async def update_one(self, query, update):
        doc = next((d for d in self.docs if matches(d, query)), None)
        if doc:
            doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=bool(doc))


def context(role, user_id="u1", employee_id=None, org_id="org1"):
    user = {"id": user_id, "email": f"{user_id}@test", "employee_id": employee_id}
    return Context(user, org_id, role)


def install_employee_db(monkeypatch):
    db = SimpleNamespace(
        employees=Collection([
            {"id": "manager", "org_id": "org1", "user_id": "mgr-user", "name": "Manager"},
            {"id": "team-emp", "org_id": "org1", "reporting_manager_id": "manager", "name": "Team"},
            {"id": "other-emp", "org_id": "org1", "reporting_manager_id": "other-manager", "name": "Other"},
            {"id": "tenant-emp", "org_id": "org2", "reporting_manager_id": "manager", "name": "Tenant"},
        ]),
        salary_assignments=Collection([
            {"employee_id": "team-emp", "org_id": "org1", "active": True, "gross_monthly": 50000,
             "structure_id": "structure", "created_at": "2026-01-01"},
        ]),
        salary_structures=Collection([{"id": "structure", "org_id": "org1", "components": []}]),
        tax_declarations=Collection(),
        tax_year_profiles=Collection(),
        tax_year_declarations=Collection(),
    )
    monkeypatch.setattr(employees, "db", db)
    monkeypatch.setattr(tax, "db", db)
    monkeypatch.setattr(tax_year_profiles, "db", db)
    async def no_emit(*args, **kwargs):
        return None
    monkeypatch.setattr(tax_year_profiles, "emit", no_emit)
    monkeypatch.setattr(team_scope, "db", db)
    return db


@pytest.mark.asyncio
async def test_manager_employee_access_is_limited_to_direct_reports(monkeypatch):
    install_employee_db(monkeypatch)
    manager = context("MANAGER", "mgr-user")
    with pytest.raises(HTTPException) as denied:
        await employees.get_employee("other-emp", manager)
    assert denied.value.status_code == 404

    allowed = await employees.get_employee("team-emp", manager)
    assert allowed["employee"]["id"] == "team-emp"


@pytest.mark.asyncio
async def test_manager_attendance_and_leave_reads_are_team_scoped(monkeypatch):
    fake = install_employee_db(monkeypatch)
    fake.attendance = Collection([
        {"id": "att-team", "org_id": "org1", "employee_id": "team-emp", "date": "2026-04-01"},
        {"id": "att-other", "org_id": "org1", "employee_id": "other-emp", "date": "2026-04-01"},
    ])
    fake.leave_balances = Collection([
        {"id": "bal-team", "org_id": "org1", "employee_id": "team-emp"},
        {"id": "bal-other", "org_id": "org1", "employee_id": "other-emp"},
    ])
    fake.leave_requests = Collection([
        {"id": "leave-team", "org_id": "org1", "employee_id": "team-emp"},
        {"id": "leave-other", "org_id": "org1", "employee_id": "other-emp"},
    ])
    monkeypatch.setattr(attendance, "db", fake)
    monkeypatch.setattr(leave, "db", fake)
    manager = context("MANAGER", "mgr-user")

    att = await attendance.list_attendance(manager, "other-emp")
    with pytest.raises(HTTPException) as denied:
        await leave.balances(manager, "other-emp")
    requests = await leave.list_requests(manager, employee_id="other-emp")
    assert att == []
    assert denied.value.status_code == 404
    assert requests == []

    assert [row["id"] for row in await attendance.list_attendance(manager)] == ["att-team"]
    assert [row["id"] for row in await leave.balances(manager, "team-emp")] == ["bal-team"]
    assert [row["id"] for row in await leave.list_requests(manager)] == ["leave-team"]


@pytest.mark.asyncio
async def test_employee_cross_tenant_access_is_blocked(monkeypatch):
    install_employee_db(monkeypatch)
    with pytest.raises(HTTPException) as denied:
        await employees.get_employee("tenant-emp", context("COMPANY_ADMIN", org_id="org1"))
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_employee_tax_declaration_is_own_only(monkeypatch):
    db = install_employee_db(monkeypatch)
    emp = db.employees.docs[1]
    emp["user_id"] = "employee-user"
    employee_ctx = context("EMPLOYEE", "employee-user", "team-emp")
    with pytest.raises(HTTPException) as denied:
        await tax.get_declarations("other-emp", employee_ctx)
    assert denied.value.status_code == 403
    assert (await tax.get_declarations(None, employee_ctx))["deduction_80c"] == 0


@pytest.mark.asyncio
async def test_manager_without_tax_permission_cannot_read_other_declaration(monkeypatch):
    install_employee_db(monkeypatch)
    with pytest.raises(HTTPException) as denied:
        await tax.get_declarations("team-emp", context("MANAGER", "mgr-user"))
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_tax_manage_role_can_view_and_update_declaration(monkeypatch):
    db = install_employee_db(monkeypatch)
    payroll = context("PAYROLL_ADMIN")
    result = await tax.put_declarations(tax.DeclarationsIn(deduction_80c=1000), "team-emp", payroll)
    assert result["deduction_80c"] == 1000
    assert (await tax.get_declarations("team-emp", payroll))["deduction_80c"] == 1000
    assert all(d["org_id"] == "org1" for d in db.tax_year_declarations.docs)


@pytest.mark.asyncio
async def test_salary_fields_require_salary_view_permission(monkeypatch):
    install_employee_db(monkeypatch)
    finance = context("FINANCE")
    without = await employees.list_employees(finance, page=1, limit=20)
    assert "gross_monthly" not in without["items"][0]
    detail = await employees.get_employee("team-emp", finance)
    assert detail["assignments"] == []
    assert detail["structures"] == []

    with_salary = await employees.list_employees(context("HR_ADMIN"), page=1, limit=20)
    team_item = next(item for item in with_salary["items"] if item["id"] == "team-emp")
    assert team_item["gross_monthly"] == 50000
    detail_with_salary = await employees.get_employee("team-emp", context("HR_ADMIN"))
    assert detail_with_salary["assignments"][0]["gross_monthly"] == 50000


@pytest.mark.asyncio
async def test_report_salary_fields_are_hidden_and_cannot_be_selected(monkeypatch):
    finance = context("FINANCE")
    listed = await reports.datasets(finance)
    payroll_ds = next(d for d in listed["datasets"] if d["key"] == "payroll_register")
    assert "gross_earnings" not in {f["key"] for f in payroll_ds["fields"]}
    with pytest.raises(HTTPException) as denied:
        await reports.run_report(reports.ReportRun(dataset="payroll_register", fields=["net_pay"]), finance)
    assert denied.value.status_code == 403

    admin_ds = await reports.datasets(context("HR_ADMIN"))
    admin_payroll = next(d for d in admin_ds["datasets"] if d["key"] == "payroll_register")
    assert "net_pay" in {f["key"] for f in admin_payroll["fields"]}
