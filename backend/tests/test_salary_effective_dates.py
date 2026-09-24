"""Salary assignment selection by payroll period."""

import pytest

from services import payroll_engine, payroll_service


def assignment(assignment_id, effective_from, gross, structure_id="structure-a", **extra):
    return {
        "id": assignment_id, "org_id": "org-1", "employee_id": "emp-1",
        "structure_id": structure_id, "gross_monthly": gross,
        "effective_from": effective_from, "active": True, **extra,
    }


def structures():
    return {
        "structure-a": {
            "id": "structure-a", "org_id": "org-1", "name": "Structure A",
            "components": [{"code": "BASIC", "name": "Basic", "calc": "pct_gross",
                            "value": 40, "taxable": True}],
        },
        "structure-b": {
            "id": "structure-b", "org_id": "org-1", "name": "Structure B",
            "components": [{"code": "BASIC", "name": "Basic", "calc": "pct_gross",
                            "value": 50, "taxable": True}],
        },
    }


def resolve(assignments, period, structure_map=None):
    return payroll_service.resolve_salary_for_period(
        assignments, structure_map or structures(), "org-1", "emp-1", period)


def test_ordinary_payroll_month_uses_effective_assignment_and_its_structure():
    selected, structure = resolve([assignment("a1", "2025-01-01", 50000, "structure-a")], "2025-03")
    components = payroll_engine.monthly_components(structure, selected["gross_monthly"])

    assert selected["id"] == "a1"
    assert structure["id"] == "structure-a"
    assert components[0]["monthly"] == 20000


def test_future_dated_assignment_is_excluded_from_earlier_payroll():
    selected, _ = resolve([
        assignment("old", "2025-01-01", 50000, active=False),
        assignment("future", "2025-08-01", 70000),
    ], "2025-07")

    assert selected["id"] == "old"
    assert selected["gross_monthly"] == 50000


def test_expired_assignment_is_excluded_when_a_valid_assignment_exists():
    selected, _ = resolve([
        assignment("expired", "2025-01-01", 50000, effective_to="2025-06-30", active=False),
        assignment("current", "2025-07-01", 60000),
    ], "2025-07")

    assert selected["id"] == "current"


def test_salary_change_between_months_uses_old_then_new_assignment():
    history = [
        assignment("old", "2025-01-01", 50000, active=False),
        assignment("new", "2025-06-01", 65000),
    ]

    april, _ = resolve(history, "2025-04")
    june, _ = resolve(history, "2025-06")
    assert (april["id"], april["gross_monthly"]) == ("old", 50000)
    assert (june["id"], june["gross_monthly"]) == ("new", 65000)


def test_overlapping_assignments_select_latest_effective_record_deterministically():
    history = [
        assignment("earlier", "2025-01-01", 50000),
        assignment("latest", "2025-05-01", 65000, "structure-b"),
        assignment("future", "2025-08-01", 70000),
    ]

    first, first_structure = resolve(history, "2025-06")
    second, _ = resolve(list(reversed(history)), "2025-06")
    assert first["id"] == second["id"] == "latest"
    assert first_structure["id"] == "structure-b"
    assert payroll_engine.monthly_components(first_structure, first["gross_monthly"])[0]["monthly"] == 32500


def test_missing_valid_assignment_fails_safely():
    with pytest.raises(ValueError, match="No salary assignment effective for payroll period 2025-04"):
        resolve([assignment("future", "2025-05-01", 70000)], "2025-04")


def test_cross_tenant_assignment_and_structure_cannot_be_selected():
    foreign = assignment("foreign", "2024-01-01", 99999)
    foreign["org_id"] = "org-2"
    foreign["structure_id"] = "foreign-structure"

    with pytest.raises(ValueError, match="No salary assignment effective"):
        resolve([foreign], "2025-04", {
            "foreign-structure": {"id": "foreign-structure", "org_id": "org-2", "components": []},
        })

    with pytest.raises(ValueError, match="not found in this organisation"):
        resolve([assignment("bad-structure", "2024-01-01", 50000, "foreign-structure")],
                "2025-04", {
                    "foreign-structure": {
                        "id": "foreign-structure", "org_id": "org-2", "components": [],
                    },
                })
