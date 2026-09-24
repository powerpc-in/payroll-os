from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from lib.auth import Context
from routers import tax
from services import employment_statutory_profiles as employment_profiles
from services import tax_year_profiles as tax_profiles
from services import payroll_service
from services.rules import RuleUnavailable


class Cursor:
    def __init__(self, docs):
        self.docs = deepcopy(list(docs))

    def sort(self, *args):
        return self

    async def to_list(self, limit):
        return deepcopy(self.docs[:limit])


class Collection:
    def __init__(self, docs=()):
        self.docs = deepcopy(list(docs))

    async def find_one(self, query, projection=None):
        return deepcopy(next((d for d in self.docs if all(d.get(k) == v for k, v in query.items())), None))

    def find(self, query, projection=None):
        return Cursor([d for d in self.docs if all(d.get(k) == v for k, v in query.items())])

    async def insert_one(self, doc):
        self.docs.append(deepcopy(doc))

    async def update_one(self, query, update):
        doc = next((d for d in self.docs if all(d.get(k) == v for k, v in query.items())), None)
        if doc:
            doc.update(deepcopy(update.get("$set", {})))


def context(role, employee_id=None, user_id="user-1", org_id="org-1"):
    return Context({"id": user_id, "email": "actor@example.test", "employee_id": employee_id}, org_id, role)


def install_db(monkeypatch, employees=()):
    fake = SimpleNamespace(
        employees=Collection(employees),
        tax_year_profiles=Collection(),
        tax_year_declarations=Collection(),
    )
    monkeypatch.setattr(tax, "db", fake)
    monkeypatch.setattr(tax_profiles, "db", fake)

    async def no_emit(*args, **kwargs):
        return None

    monkeypatch.setattr(tax_profiles, "emit", no_emit)
    return fake


def prof(fy, regime="new", residency="resident_ordinary", **extra):
    return {"id": f"{fy}-{regime}", "org_id": "org-1", "employee_id": "emp-1",
            "financial_year": fy, "tax_regime": regime,
            "tax_residency_status": residency, **extra}


@pytest.mark.asyncio
async def test_create_and_update_tax_year_profile_preserves_other_years(monkeypatch):
    fake = install_db(monkeypatch, [{"id": "emp-1", "org_id": "org-1", "user_id": "employee-1"}])
    payroll = context("PAYROLL_ADMIN")
    first = await tax.put_tax_profile(
        tax_profiles.TaxYearProfileIn(financial_year="2025-26", tax_regime="old",
                                      tax_residency_status="resident_ordinary"),
        "emp-1", payroll)
    current = await tax.put_tax_profile(
        tax_profiles.TaxYearProfileIn(financial_year="2026-27", tax_regime="new",
                                      tax_residency_status="resident_not_ordinary"),
        "emp-1", payroll)
    assert first["financial_year"] == "2025-26"
    assert current["financial_year"] == "2026-27"
    assert len(fake.tax_year_profiles.docs) == 2
    revised = await tax.put_tax_profile(
        tax_profiles.TaxYearProfileIn(financial_year="2026-27", tax_regime="old",
                                      tax_residency_status="resident_not_ordinary"),
        "emp-1", payroll)
    assert revised["tax_regime"] == "old"
    assert len(fake.tax_year_profiles.docs) == 2
    assert fake.tax_year_profiles.docs[0]["created_by"] == payroll.user_id


def test_period_maps_to_indian_financial_year():
    assert tax_profiles.financial_year_key("2026-08") == "2026-27"
    assert tax_profiles.financial_year_key("2026-03") == "2025-26"


@pytest.mark.asyncio
async def test_prior_and_future_year_profiles_do_not_leak_into_current_fy(monkeypatch):
    fake = install_db(monkeypatch)
    fake.tax_year_profiles = Collection([
        prof("2025-26", regime="old"), prof("2027-28", regime="old"),
    ])
    monkeypatch.setattr(tax_profiles, "db", fake)
    result = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "tax_regime": "new"}, "2026-08")
    assert result["financial_year"] == "2026-27"
    assert result["profile"] is None
    assert result["employee_overrides"]["tax_regime"] == "new"


def test_duplicate_year_profile_resolution_is_deterministic():
    rows = [prof("2026-27", id="older", updated_at="2026-04-01"),
            prof("2026-27", id="newer", updated_at="2026-07-01")]
    selected = tax_profiles.select_tax_year_profile(rows, "org-1", "emp-1", "2026-27")
    assert selected["id"] == "newer"
    assert tax_profiles.select_tax_year_profile(rows, "org-2", "emp-1", "2026-27") is None


@pytest.mark.asyncio
async def test_tax_profile_lookup_is_tenant_scoped(monkeypatch):
    fake = install_db(monkeypatch)
    fake.tax_year_profiles = Collection([prof("2026-27", org_id="org-2")])
    monkeypatch.setattr(tax_profiles, "db", fake)
    result = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "tax_regime": "new"}, "2026-08")
    assert result["profile"] is None


@pytest.mark.asyncio
async def test_employee_cannot_modify_employer_controlled_tax_profile(monkeypatch):
    fake = install_db(monkeypatch,
                      [{"id": "emp-1", "org_id": "org-1", "user_id": "employee-1"}])
    employee = context("EMPLOYEE", employee_id="emp-1", user_id="employee-1")
    request = tax_profiles.TaxYearProfileIn(financial_year="2026-27", tax_regime="new",
                                            tax_residency_status="resident_ordinary")
    with pytest.raises(HTTPException) as exc:
        await tax.put_tax_profile(request, None, employee)
    assert exc.value.status_code == 403
    assert fake.tax_year_profiles.docs == []
    with pytest.raises(ValidationError):
        tax.DeclarationsIn.model_validate({"tax_regime": "old"})


@pytest.mark.asyncio
async def test_manager_tax_profile_access_remains_restricted(monkeypatch):
    install_db(monkeypatch, [{"id": "emp-1", "org_id": "org-1", "user_id": "employee-1"}])
    with pytest.raises(HTTPException) as exc:
        await tax.get_tax_profile("emp-1", "2026-27", context("MANAGER"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_profile_regime_overrides_legacy_employee_regime(monkeypatch):
    fake = install_db(monkeypatch)
    fake.tax_year_profiles = Collection([prof("2026-27", regime="old")])
    monkeypatch.setattr(tax_profiles, "db", fake)
    result = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "tax_regime": "new"}, "2026-08")
    assert result["employee_overrides"]["tax_regime"] == "old"
    assert result["employee_overrides"]["tax_residency_status"] == "resident_ordinary"


@pytest.mark.asyncio
async def test_payroll_rule_resolver_uses_tax_year_regime(monkeypatch):
    fake = install_db(monkeypatch)
    fake.tax_year_profiles = Collection([prof("2026-27", regime="old")])
    employment_db = SimpleNamespace(
        employment_statutory_profiles=Collection(), locations=Collection(), statutory_establishments=Collection())
    monkeypatch.setattr(tax_profiles, "db", fake)
    monkeypatch.setattr(employment_profiles, "db", employment_db)
    calls = []

    async def fake_rule(org_id, jurisdiction, rule_type, on_date, state=None, allow_unverified=False):
        calls.append(rule_type)
        return {"id": rule_type, "rule_type": rule_type, "verified": True, "params": {}}

    monkeypatch.setattr(payroll_service, "get_rule", fake_rule)
    context_for_period = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "tax_regime": "new"}, "2026-08")
    await payroll_service.resolve_employee_rules(
        {"id": "org-1", "jurisdiction": "IN", "payroll_settings": {}},
        {"id": "emp-1", "tax_regime": "new", **context_for_period["employee_overrides"],
         "pf_applicable": False, "esi_applicable": False, "pt_applicable": False, "lwf_applicable": False},
        "2026-08-01")
    assert calls == ["income_tax_old_regime"]


@pytest.mark.asyncio
async def test_payroll_resolver_fails_closed_when_residency_required_but_missing(monkeypatch):
    employment_db = SimpleNamespace(
        employment_statutory_profiles=Collection(), locations=Collection(), statutory_establishments=Collection())
    monkeypatch.setattr(employment_profiles, "db", employment_db)

    async def fake_rule(org_id, jurisdiction, rule_type, on_date, state=None, allow_unverified=False):
        return {"id": "tax-rule", "rule_type": rule_type, "verified": True,
                "params": {"rebate": {"taxable_limit": 100}}}

    monkeypatch.setattr(payroll_service, "get_rule", fake_rule)
    with pytest.raises(RuleUnavailable, match="Tax residency status is required"):
        await payroll_service.resolve_employee_rules(
            {"id": "org-1", "jurisdiction": "IN", "payroll_settings": {"accept_unverified_statutory_values": True}},
            {"id": "emp-1", "tax_regime": "new", "pf_applicable": False,
             "esi_applicable": False, "pt_applicable": False, "lwf_applicable": False},
            "2026-08-01")


@pytest.mark.asyncio
async def test_legacy_employee_without_profile_uses_legacy_regime(monkeypatch):
    install_db(monkeypatch)
    result = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "tax_regime": "old"}, "2026-08")
    assert result["profile"] is None
    assert result["employee_overrides"]["tax_regime"] == "old"
    assert result["employee_overrides"]["tax_residency_status"] is None


@pytest.mark.asyncio
async def test_declarations_are_saved_and_resolved_by_financial_year(monkeypatch):
    fake = install_db(monkeypatch)
    declarations = tax_profiles.TaxYearDeclarationsIn(deduction_80c=1000)
    old = await tax_profiles.upsert_declarations("org-1", "emp-1", "2025-26", declarations,
                                                  {"id": "payroll-user"})
    current = await tax_profiles.upsert_declarations("org-1", "emp-1", "2026-27",
                                                      tax_profiles.TaxYearDeclarationsIn(deduction_80c=2000),
                                                      {"id": "payroll-user"})
    context_for_period = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1"}, "2026-08")
    assert old["financial_year"] == "2025-26"
    assert current["financial_year"] == "2026-27"
    assert context_for_period["declarations"]["deduction_80c"] == 2000
    assert len(fake.tax_year_declarations.docs) == 2


@pytest.mark.parametrize("field", ["deduction_80c", "deduction_80d", "annual_rent_paid", "other_income"])
def test_negative_tax_declaration_amounts_remain_rejected(field):
    with pytest.raises(ValidationError):
        tax.DeclarationsIn(**{field: -1})


@pytest.mark.asyncio
async def test_hra_residence_context_is_independent_of_work_location(monkeypatch):
    fake = install_db(monkeypatch)
    await tax_profiles.upsert_declarations(
        "org-1", "emp-1", "2026-27",
        tax_profiles.TaxYearDeclarationsIn(
            annual_rent_paid=120000, rent_period_start=date(2026, 4, 1),
            rent_period_end=date(2027, 3, 31), residence_city="Bengaluru",
            residence_location="Jayanagar", metro=True), {"id": "employee-1"})
    result = await tax_profiles.resolve_tax_year_context(
        "org-1", {"id": "emp-1", "work_state": "MH"}, "2026-08")
    decl = result["declarations"]
    assert decl["residence_city"] == "Bengaluru"
    assert decl["residence_location"] == "Jayanagar"
    assert decl["metro"] is True
    assert "work_state" not in decl
    assert len(fake.tax_year_declarations.docs) == 1


def test_missing_and_nonresident_status_fail_closed_for_resident_only_rebate_rule():
    rule = {"rule_type": "income_tax_new_regime", "params": {"rebate": {"taxable_limit": 100}}}
    with pytest.raises(RuleUnavailable, match="Tax residency status is required"):
        tax_profiles.require_supported_residency(rule, None, "IN")
    with pytest.raises(RuleUnavailable, match="cannot safely apply"):
        tax_profiles.require_supported_residency(rule, "non_resident", "IN")
    with pytest.raises(RuleUnavailable, match="does not encode rebate eligibility"):
        tax_profiles.require_supported_residency(rule, "resident_not_ordinary", "IN")


@pytest.mark.asyncio
async def test_rent_period_must_fit_selected_financial_year(monkeypatch):
    fake = install_db(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await tax_profiles.upsert_declarations(
            "org-1", "emp-1", "2026-27",
            tax_profiles.TaxYearDeclarationsIn(
                annual_rent_paid=1, rent_period_start=date(2025, 4, 1),
                rent_period_end=date(2026, 3, 31), residence_city="Bengaluru", metro=True),
            {"id": "actor"})
    assert exc.value.status_code == 422
    assert fake.tax_year_declarations.docs == []
