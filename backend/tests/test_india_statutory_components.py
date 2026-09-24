"""Deterministic component-formula and rule-resolution regression tests.

Synthetic rule parameters below exercise calculation mechanics only. Seeded rule
metadata is tested separately for verification status and effective-date safety.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

import seed
from services import payroll_engine, payroll_service, rules as rule_service
from services.rules import RuleUnavailable


class RuleCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, field, direction):
        self.documents.sort(key=lambda d: d.get(field, 0), reverse=direction < 0)
        return self

    async def to_list(self, length):
        return deepcopy(self.documents[:length])


def _matches(document, query):
    for key, expected in query.items():
        if key == "$and":
            if not all(_matches(document, item) for item in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        value = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$lte" in expected and (value is None or value > expected["$lte"]):
                return False
            if "$gte" in expected and (value is None or value < expected["$gte"]):
                return False
            if "$exists" in expected and ((key in document) != expected["$exists"]):
                return False
        elif value != expected:
            # Mongo matches null equality against a missing field as well.
            if not (expected is None and key not in document):
                return False
    return True


class RuleCollection:
    def __init__(self, documents):
        self.documents = deepcopy(documents)

    def find(self, query):
        return RuleCursor([d for d in self.documents if _matches(d, query)])


def rule(rule_type, params, *, verified=True, state=None, org_id="org-1"):
    return {
        "id": f"{rule_type}-{state or 'national'}-{org_id}", "org_id": org_id,
        "jurisdiction": "IN", "rule_type": rule_type, "state": state,
        "params": params, "effective_from": "2025-04-01", "effective_to": None,
        "active": True, "version": 1, "source": "test rule", "verified": verified,
    }


def payroll_result(*, period="2025-04", gross=50000, absent=0, employee_overrides=None,
                   components=None, statutory=None):
    employee = {
        "id": "emp-1", "name": "Test", "pf_applicable": True, "esi_applicable": True,
        "pt_applicable": True, "lwf_applicable": True,
        **(employee_overrides or {}),
    }
    structure = {"components": components or [{
        "code": "BASIC", "name": "Basic", "calc": "fixed", "value": gross,
        "taxable": True, "pf_applicable": True, "esi_applicable": True,
    }]}
    rules = {"income_tax": None, "pf": None, "esi": None, "pt": None, "lwf": None}
    rules.update(statutory or {})
    return payroll_engine.compute_employee_payroll(
        employee=employee, period=period, assignment={"gross_monthly": gross}, structure=structure,
        attendance_summary={"absent": absent}, inputs=[], loan_items=[], declarations={}, ytd_tds=0,
        rules=rules, months_elapsed_in_fy=1, accept_unverified=False,
    )


def amount(rows, code):
    return next(row["amount"] for row in rows if row["code"] == code)


PF_TEST_RULE = {
    "employee_rate": 0.10, "employer_rate": 0.12, "eps_rate": 0.08, "wage_ceiling": 15000,
}


@pytest.mark.parametrize(("higher_wages", "employee_pf", "employer_epf", "employer_eps"), [
    (False, 1500, 600, 1200),
    (True, 3000, 2400, 1200),
])
def test_pf_wage_ceiling_and_higher_wage_opt_in(higher_wages, employee_pf, employer_epf, employer_eps):
    result = payroll_result(
        gross=30000, employee_overrides={"pf_on_higher_wages": higher_wages},
        statutory={"pf": rule("provident_fund", PF_TEST_RULE)},
    )

    assert amount(result["deductions"], "PF") == employee_pf
    assert amount(result["employer_contributions"], "EPF_ER") == employer_epf
    assert amount(result["employer_contributions"], "EPS_ER") == employer_eps


def test_pf_without_rule_ceiling_uses_full_pf_wage():
    unbounded = {**PF_TEST_RULE, "wage_ceiling": None}
    result = payroll_result(
        gross=50000, statutory={"pf": rule("provident_fund", unbounded)})

    assert amount(result["deductions"], "PF") == 5000
    assert amount(result["employer_contributions"], "EPF_ER") == 2000
    assert amount(result["employer_contributions"], "EPS_ER") == 4000


def test_pf_ceiling_and_eps_wages_are_prorated_for_lop():
    result = payroll_result(
        gross=30000, absent=10,
        statutory={"pf": rule("provident_fund", PF_TEST_RULE)})

    assert amount(result["deductions"], "PF") == 1000
    assert amount(result["employer_contributions"], "EPF_ER") == 400
    assert amount(result["employer_contributions"], "EPS_ER") == 800


def test_pf_not_calculated_when_employee_is_not_applicable():
    result = payroll_result(
        employee_overrides={"pf_applicable": False},
        statutory={"pf": rule("provident_fund", PF_TEST_RULE)})
    assert not any(row["code"] == "PF" for row in result["deductions"])
    assert not any(row["code"] in ("EPF_ER", "EPS_ER") for row in result["employer_contributions"])


ESI_TEST_RULE = {"employee_rate": 0.01, "employer_rate": 0.02, "gross_limit": 21000}


def test_esi_eligible_employee_amounts_use_rule_rates():
    result = payroll_result(
        gross=20000, statutory={"esi": rule("employee_state_insurance", ESI_TEST_RULE)})

    assert amount(result["deductions"], "ESI") == 200
    assert amount(result["employer_contributions"], "ESI_ER") == 400


def test_esi_employee_above_threshold_has_no_contribution():
    result = payroll_result(
        gross=22000, statutory={"esi": rule("employee_state_insurance", ESI_TEST_RULE)})

    assert not any(row["code"] == "ESI" for row in result["deductions"])
    assert not any(row["code"] == "ESI_ER" for row in result["employer_contributions"])


def test_esi_lop_uses_full_month_eligibility_and_reduced_payable_wage():
    result = payroll_result(
        gross=20000, absent=15,
        statutory={"esi": rule("employee_state_insurance", ESI_TEST_RULE)})

    assert amount(result["deductions"], "ESI") == 100
    assert amount(result["employer_contributions"], "ESI_ER") == 200


def test_esi_excludes_components_marked_not_applicable():
    components = [
        {"code": "BASIC", "name": "Basic", "calc": "fixed", "value": 15000,
         "pf_applicable": True, "esi_applicable": True},
        {"code": "ALLOW", "name": "Allowance", "calc": "fixed", "value": 10000,
         "pf_applicable": False, "esi_applicable": False},
    ]
    result = payroll_result(
        gross=25000, components=components,
        statutory={"esi": rule("employee_state_insurance", ESI_TEST_RULE)})

    assert amount(result["deductions"], "ESI") == 150
    assert amount(result["employer_contributions"], "ESI_ER") == 300


def test_pt_uses_karnataka_seed_rule_and_employee_applicability():
    params = next(x["params"] for x in seed.STATUTORY_RULES
                  if x["rule_type"] == "professional_tax" and x["state"] == "KA")
    pt_rule = rule("professional_tax", params, verified=False, state="KA")
    result = payroll_result(
        gross=30000, statutory={"pt": pt_rule})
    disabled = payroll_result(
        gross=30000, employee_overrides={"pt_applicable": False}, statutory={"pt": pt_rule})

    assert amount(result["deductions"], "PT") == params["slabs"][0]["amount"]
    assert not any(row["code"] == "PT" for row in disabled["deductions"])


@pytest.mark.parametrize("period,expected", [("2025-05", False), ("2025-06", True), ("2025-12", True)])
def test_lwf_deduction_occurs_only_in_rule_due_months(period, expected):
    lwf = {"employee": 12, "employer": 36, "frequency": "half_yearly", "deduction_months": [6, 12]}
    result = payroll_result(
        period=period, statutory={"lwf": rule("lwf", lwf, verified=False, state="KA")})

    assert any(row["code"] == "LWF" for row in result["deductions"]) is expected
    assert any(row["code"] == "LWF_ER" for row in result["employer_contributions"]) is expected
    if expected:
        assert amount(result["deductions"], "LWF") == 12
        assert amount(result["employer_contributions"], "LWF_ER") == 36


def test_seeded_karnataka_lwf_without_schedule_fails_safely():
    params = next(x["params"] for x in seed.STATUTORY_RULES
                  if x["rule_type"] == "lwf" and x["state"] == "KA")
    assert "frequency" not in params and "deduction_months" not in params
    with pytest.raises(ValueError, match="LWF rule must define deduction_months"):
        payroll_result(statutory={"lwf": rule("lwf", params, verified=False, state="KA")})


def test_lwf_empty_due_month_schedule_never_deducts():
    lwf = {"employee": 12, "employer": 36, "frequency": "half_yearly", "deduction_months": []}
    result = payroll_result(
        period="2025-06", statutory={"lwf": rule("lwf", lwf, state="KA")})
    assert not any(row["code"] == "LWF" for row in result["deductions"])
    assert not any(row["code"] == "LWF_ER" for row in result["employer_contributions"])


@pytest.mark.asyncio
async def test_state_rule_resolution_respects_org_state_jurisdiction_and_effective_dates(monkeypatch):
    seeded_ka = next(x for x in seed.STATUTORY_RULES
                     if x["rule_type"] == "professional_tax" and x["state"] == "KA")
    documents = [
        rule("professional_tax", seeded_ka["params"], verified=False, state="KA", org_id="org-1"),
        {**rule("professional_tax", {"slabs": []}, state="KA", org_id="org-2"), "version": 99},
        {**rule("professional_tax", {"slabs": []}, state=None, org_id=None), "version": 100},
        {**rule("professional_tax", {"slabs": []}, state="KA", org_id=None), "version": 1},
        {**rule("professional_tax", {"slabs": []}, state="KA", org_id="org-1"),
         "id": "future", "effective_from": "2026-04-01", "version": 50},
        {**rule("professional_tax", {"slabs": []}, state="KA", org_id="org-1"),
         "id": "expired", "effective_to": "2025-03-31", "version": 40},
    ]
    monkeypatch.setattr(rule_service, "db", SimpleNamespace(statutory_rules=RuleCollection(documents)))

    selected = await rule_service.get_rule(
        "org-1", "IN", "professional_tax", "2025-04-01", "KA", allow_unverified=True)
    assert selected["org_id"] == "org-1"
    assert selected["state"] == "KA"
    assert selected["verified"] is False
    with pytest.raises(RuleUnavailable, match="Requires statutory verification"):
        await rule_service.get_rule("org-1", "IN", "professional_tax", "2025-04-01", "KA")
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", "professional_tax", "2025-04-01", "MH",
                                    allow_unverified=True)
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", "professional_tax", "2025-04-01", None,
                                    allow_unverified=True)


@pytest.mark.asyncio
async def test_lwf_rule_selection_uses_seeded_state_and_fails_unverified_by_default(monkeypatch):
    seeded_ka = next(x for x in seed.STATUTORY_RULES if x["rule_type"] == "lwf" and x["state"] == "KA")
    document = rule("lwf", seeded_ka["params"], verified=False, state="KA", org_id="org-1")
    monkeypatch.setattr(rule_service, "db", SimpleNamespace(statutory_rules=RuleCollection([document])))

    with pytest.raises(RuleUnavailable, match="Requires statutory verification"):
        await rule_service.get_rule("org-1", "IN", "lwf", "2025-04-01", "KA")
    selected = await rule_service.get_rule(
        "org-1", "IN", "lwf", "2025-04-01", "KA", allow_unverified=True)
    assert selected["state"] == "KA"
    assert selected["verified"] is False
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", "lwf", "2025-04-01", "MH",
                                    allow_unverified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_type", ["professional_tax", "lwf"])
@pytest.mark.parametrize("state", ["KA", "MH", "DL", "TG"])
async def test_seeded_unverified_state_rules_stay_blocked_and_state_exact(
        rule_type, state, monkeypatch):
    spec = next(x for x in seed.STATUTORY_RULES
                if x["rule_type"] == rule_type and x["state"] == state)
    assert spec.get("verified", False) is False
    document = rule(rule_type, spec["params"], verified=False, state=state, org_id="org-1")
    monkeypatch.setattr(rule_service, "db", SimpleNamespace(
        statutory_rules=RuleCollection([document])))

    with pytest.raises(RuleUnavailable, match="Requires statutory verification"):
        await rule_service.get_rule("org-1", "IN", rule_type, "2026-08-01", state)
    selected = await rule_service.get_rule("org-1", "IN", rule_type,
                                           "2026-08-01", state, allow_unverified=True)
    assert selected["state"] == state
    assert selected["verified"] is False
    wrong_state = "MH" if state != "MH" else "KA"
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", rule_type, "2026-08-01", wrong_state,
                                    allow_unverified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_type", ["professional_tax", "lwf"])
async def test_rajasthan_state_rule_is_missing_and_fails_closed(rule_type, monkeypatch):
    docs = [rule(rule_type, spec["params"], verified=False, state=spec["state"], org_id="org-1")
            for spec in seed.STATUTORY_RULES
            if spec["rule_type"] == rule_type and spec["state"] is not None]
    monkeypatch.setattr(rule_service, "db", SimpleNamespace(
        statutory_rules=RuleCollection(docs)))

    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", rule_type, "2026-08-01", "RJ",
                                    allow_unverified=True)


@pytest.mark.asyncio
async def test_employee_work_state_is_used_for_state_rule_resolution(monkeypatch):
    calls = []

    async def fake_get_rule(org_id, jurisdiction, rule_type, on_date, state, allow_unverified):
        calls.append((rule_type, on_date, state))
        return {"id": rule_type, "verified": True}

    monkeypatch.setattr(payroll_service, "get_rule", fake_get_rule)
    result = await payroll_service.resolve_employee_rules(
        {"id": "org-1", "jurisdiction": "IN", "payroll_settings": {}},
        {"id": "emp-1", "work_state": "KA", "pf_applicable": False,
         "esi_applicable": False, "pt_applicable": True, "lwf_applicable": True},
        "2025-04-01",
    )

    assert result["pt"]["id"] == "professional_tax"
    assert ("professional_tax", "2025-04-01", "KA") in calls
    assert ("lwf", "2025-04-01", "KA") in calls


def test_seed_tax_rules_are_bounded_to_fy_2025_26():
    tax_rules = [x for x in seed.STATUTORY_RULES if x["rule_type"].startswith("income_tax_")]
    historical = [x for x in tax_rules if x.get("version", 1) == 1]
    assert len(historical) == 2
    assert all(seed.statutory_effective_dates(x) == ("2025-04-01", "2026-03-31")
               for x in historical)
    assert all("FY 2025-26 / AY 2026-27" in seed.unverified_rule_note(x["rule_type"], None)
               for x in historical)


@pytest.mark.asyncio
@pytest.mark.parametrize("rule_type", ["income_tax_new_regime", "income_tax_old_regime"])
async def test_current_tax_rule_dates_params_and_fail_closed_selection(rule_type, monkeypatch):
    spec = next(x for x in seed.STATUTORY_RULES
                if x["rule_type"] == rule_type and x.get("version") == 2)
    assert seed.statutory_effective_dates(spec) == ("2026-04-01", "2027-03-31")
    assert spec.get("verified", False) is False
    assert spec["source_date"] == "2026-03-30"
    assert "egazette.gov.in" in spec["source"]
    params = spec["params"]
    assert params["cess_rate"] == 0.04
    if rule_type == "income_tax_new_regime":
        assert [(slab["up_to"], slab["rate"]) for slab in params["slabs"]] == [
            (400000, 0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15),
            (2000000, 0.20), (2400000, 0.25), (None, 0.30),
        ]
        assert params["standard_deduction"] == 75000
        assert params["rebate"] == {"taxable_limit": 1200000, "max_rebate": 60000}
        assert [tier["rate"] for tier in params["surcharge"]] == [0.10, 0.15, 0.25, 0.25]
    else:
        assert [(slab["up_to"], slab["rate"]) for slab in params["slabs"]] == [
            (250000, 0), (500000, 0.05), (1000000, 0.20), (None, 0.30),
        ]
        assert params["standard_deduction"] == 50000
        assert params["rebate"] == {"taxable_limit": 500000, "max_rebate": 12500}
        assert [tier["rate"] for tier in params["surcharge"]] == [0.10, 0.15, 0.25, 0.37]
    document = rule(rule_type, spec["params"], verified=False)
    document.update({"version": spec["version"], "effective_from": spec["effective_from"],
                     "effective_to": spec["effective_to"], "source": spec["source"],
                     "source_date": spec["source_date"]})
    historical = rule(rule_type, {"slabs": []}, verified=True)
    historical.update({"effective_from": "2025-04-01", "effective_to": "2026-03-31"})
    monkeypatch.setattr(rule_service, "db", SimpleNamespace(
        statutory_rules=RuleCollection([historical, document])))

    selected = await rule_service.get_rule("org-1", "IN", rule_type, "2026-08-01",
                                           allow_unverified=True)
    assert selected["version"] == 2
    assert selected["params"] == spec["params"]
    with pytest.raises(RuleUnavailable, match="Requires statutory verification"):
        await rule_service.get_rule("org-1", "IN", rule_type, "2026-08-01")


@pytest.mark.asyncio
async def test_verified_esi_rule_metadata_and_effective_date(monkeypatch):
    spec = next(x for x in seed.STATUTORY_RULES
                if x["rule_type"] == "employee_state_insurance")
    assert spec["verified"] is True
    assert spec["effective_from"] == "2019-07-01"
    assert spec["source_date"] == "2026-09-24"
    assert "esic.gov.in" in spec["source"]
    document = rule(spec["rule_type"], spec["params"])
    document.update({"effective_from": spec["effective_from"], "verified": spec["verified"],
                     "source": spec["source"], "source_date": spec["source_date"]})
    monkeypatch.setattr(rule_service, "db",
                        SimpleNamespace(statutory_rules=RuleCollection([document])))

    selected = await rule_service.get_rule("org-1", "IN", spec["rule_type"],
                                           "2026-08-01", allow_unverified=False)
    assert selected["params"] == {"employee_rate": 0.0075, "employer_rate": 0.0325,
                                  "gross_limit": 21000}
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", spec["rule_type"],
                                    "2019-06-30", allow_unverified=True)


@pytest.mark.asyncio
async def test_fy_2025_26_tax_rule_does_not_resolve_for_seed_demo_period(monkeypatch):
    docs = []
    for spec in seed.STATUTORY_RULES:
        if spec["rule_type"].startswith("income_tax_") and spec.get("version", 1) == 1:
            effective_from, effective_to = seed.statutory_effective_dates(spec)
            doc = rule(spec["rule_type"], spec["params"], verified=False)
            doc.update({"effective_from": effective_from, "effective_to": effective_to})
            docs.append(doc)
    monkeypatch.setattr(rule_service, "db",
                        SimpleNamespace(statutory_rules=RuleCollection(docs)))

    with pytest.raises(RuleUnavailable, match="Requires statutory verification"):
        await rule_service.get_rule("org-1", "IN", "income_tax_new_regime",
                                    "2025-04-01", allow_unverified=False)
    with pytest.raises(RuleUnavailable, match="No active"):
        await rule_service.get_rule("org-1", "IN", "income_tax_new_regime",
                                    "2026-08-01", allow_unverified=True)
