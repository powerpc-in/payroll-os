"""Regression coverage for financial-year TDS accumulation and declaration inputs."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from routers.tax import DeclarationsIn
from services import payroll_engine
from services import payroll_service


class Cursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length):
        return deepcopy(self.documents[:length])


def _matches(document, query):
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
            if "$lt" in expected and (value is None or value >= expected["$lt"]):
                return False
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
        elif value != expected:
            return False
    return True


class Collection:
    def __init__(self, documents):
        self.documents = deepcopy(documents)

    def find(self, query):
        return Cursor([d for d in self.documents if _matches(d, query)])


def install_ytd_db(monkeypatch):
    runs = [
        {"id": "previous-fy", "org_id": "org-1", "period": "2025-03", "status": "locked"},
        {"id": "fy-start", "org_id": "org-1", "period": "2025-04", "status": "approved"},
        {"id": "not-approved", "org_id": "org-1", "period": "2025-05", "status": "review"},
        {"id": "calculated", "org_id": "org-1", "period": "2025-05", "status": "calculated"},
        {"id": "prior-current-fy", "org_id": "org-1", "period": "2025-06", "status": "locked"},
        {"id": "current", "org_id": "org-1", "period": "2025-07", "status": "calculated"},
        {"id": "next-fy", "org_id": "org-1", "period": "2026-04", "status": "locked"},
    ]
    rows = [
        {"org_id": "org-1", "employee_id": "emp-1", "run_id": run_id,
         "status": status, "tds_amount": amount}
        for run_id, status, amount in [
            ("previous-fy", "ok", 1000), ("fy-start", "ok", 100),
            ("not-approved", "ok", 2000), ("calculated", "ok", 3000),
            ("prior-current-fy", "ok", 200), ("current", "ok", 4000),
            ("next-fy", "ok", 5000), ("prior-current-fy", "error", 900),
        ]
    ]
    fake_db = SimpleNamespace(
        payroll_runs=Collection(runs), payroll_employees=Collection(rows))
    monkeypatch.setattr(payroll_service, "db", fake_db)


@pytest.mark.asyncio
async def test_ytd_tds_uses_only_approved_locked_runs_in_current_fy(monkeypatch):
    install_ytd_db(monkeypatch)
    prior_runs = await payroll_service.prior_payroll_runs("org-1", "2025-07")
    run_ids = [run["id"] for run in prior_runs]

    assert "previous-fy" not in run_ids
    assert "next-fy" not in run_ids
    assert "fy-start" in run_ids
    assert "prior-current-fy" in run_ids
    assert "not-approved" not in run_ids
    assert "calculated" not in run_ids
    assert "current" not in run_ids
    assert await payroll_service.ytd_tds_for_employee("org-1", "emp-1", run_ids) == 300


def test_indian_fy_month_count_is_based_on_payroll_period():
    assert payroll_engine.fy_of_period("2025-03") == (2024, 12, "FY 2024-25")
    assert payroll_engine.fy_of_period("2025-04") == (2025, 1, "FY 2025-26")
    assert payroll_engine.fy_of_period("2026-03") == (2025, 12, "FY 2025-26")


def test_payroll_tds_uses_annual_projection_and_deducts_prior_ytd(monkeypatch):
    employee = {
        "id": "emp-1", "name": "Test Employee", "tax_regime": "new",
        "pf_applicable": False, "esi_applicable": False,
        "pt_applicable": False, "lwf_applicable": False,
    }
    assignment = {"gross_monthly": 10000}
    structure = {"components": [{
        "code": "BASIC", "name": "Basic", "calc": "pct_gross", "value": 100,
        "taxable": True,
    }]}
    tax_rule = {
        "id": "test-tax-rule", "rule_type": "income_tax_new_regime", "verified": True,
        "params": {
            "standard_deduction": 0,
            "slabs": [{"up_to": None, "rate": 0.10}],
            "surcharge": [], "cess_rate": 0,
        },
    }

    result = payroll_engine.compute_employee_payroll(
        employee=employee, period="2025-09", assignment=assignment, structure=structure,
        attendance_summary={}, inputs=[], loan_items=[], declarations={}, ytd_tds=4500,
        rules={"income_tax": tax_rule, "pf": None, "esi": None, "pt": None, "lwf": None},
        months_elapsed_in_fy=6, accept_unverified=False,
    )

    tds = next(row["amount"] for row in result["deductions"] if row["code"] == "TDS")
    assert tds == 1500
    assert "Projected taxable 120,000 gross" in next(
        row["explanation"]["input"] for row in result["deductions"] if row["code"] == "TDS")


@pytest.mark.parametrize("field", ["deduction_80c", "deduction_80d", "annual_rent_paid", "other_income"])
def test_negative_tax_declaration_amounts_are_rejected(field):
    with pytest.raises(ValidationError):
        DeclarationsIn(**{field: -1})


def test_zero_tax_declaration_amounts_remain_valid():
    declaration = DeclarationsIn(
        deduction_80c=0, deduction_80d=0, annual_rent_paid=0, other_income=0)
    assert declaration.model_dump() == {
        "deduction_80c": 0, "deduction_80d": 0, "annual_rent_paid": 0,
        "other_income": 0, "rent_period_start": None, "rent_period_end": None,
        "residence_city": None, "residence_location": None, "metro": None,
    }
