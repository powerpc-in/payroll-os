from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from lib.auth import Context, require_perm
from lib.rbac import has_permission
from services import employment_statutory_profiles as profiles
from services import payroll_service
from services.rules import RuleUnavailable
from services.statutory_profile_models import EmploymentStatutoryProfileIn, StatutoryEstablishmentIn


class Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *args):
        return self

    def to_list(self, limit):
        async def result():
            return self.docs[:limit]
        return result()


class Collection:
    def __init__(self, docs=()):
        self.docs = list(docs)

    async def find_one(self, query, projection=None):
        return next((dict(d) for d in self.docs
                     if all(d.get(k) == v for k, v in query.items())), None)

    def find(self, query, projection=None):
        return Cursor([d for d in self.docs if all(d.get(k) == v for k, v in query.items())])

    async def insert_one(self, document):
        self.docs.append(dict(document))


def profile_doc(profile_id, start, end=None, **extra):
    return {"id": profile_id, "org_id": "org-1", "employee_id": "emp-1",
            "effective_from": start, "effective_to": end, **extra}


def test_effective_profile_selection_current_future_expired_and_overlap_is_deterministic():
    rows = [
        profile_doc("old", "2025-01-01", "2025-12-31"),
        profile_doc("current-a", "2026-01-01", None, created_at="2026-01-01T00:00:00Z"),
        profile_doc("current-b", "2026-01-01", None, created_at="2026-01-01T00:00:00Z"),
        profile_doc("future", "2026-09-01"),
    ]
    selected = profiles.select_effective_profile(rows, "org-1", "emp-1", "2026-08-01")
    assert selected["id"] == "current-b"
    assert profiles.select_effective_profile(rows, "other-org", "emp-1", "2026-08-01") is None


@pytest.mark.asyncio
async def test_create_and_future_update_append_profiles_without_overwriting_history(monkeypatch):
    from routers import statutory_profiles as routes

    employees = Collection([{"id": "emp-1", "org_id": "org-1"}])
    records = Collection()
    monkeypatch.setattr(profiles, "db", SimpleNamespace(
        employees=employees, employment_statutory_profiles=records,
        locations=Collection(), statutory_establishments=Collection()))
    monkeypatch.setattr(routes, "db", SimpleNamespace(
        employees=employees, employment_statutory_profiles=records,
        locations=Collection(), statutory_establishments=Collection()))
    actor = Context({"id": "admin", "email": "admin@example.test"}, "org-1", "COMPANY_ADMIN")

    first = await routes.add_employee_profile(
        "emp-1", EmploymentStatutoryProfileIn(effective_from=date(2026, 1, 1), work_state="KA"), actor)
    future = await routes.add_employee_profile(
        "emp-1", EmploymentStatutoryProfileIn(effective_from=date(2026, 9, 1), work_state="MH"), actor)
    assert first["effective_from"] == "2026-01-01"
    assert future["effective_from"] == "2026-09-01"
    assert len(records.docs) == 2
    assert profiles.select_effective_profile(records.docs, "org-1", "emp-1", "2026-08-01")["work_state"] == "KA"
    assert profiles.select_effective_profile(records.docs, "org-1", "emp-1", "2026-09-01")["work_state"] == "MH"


@pytest.mark.asyncio
async def test_expired_profile_is_not_selected_for_payroll_period(monkeypatch):
    docs = Collection([profile_doc("expired", "2025-01-01", "2025-12-31")])
    monkeypatch.setattr(profiles, "db", SimpleNamespace(employment_statutory_profiles=docs))
    assert await profiles.current_profile("org-1", "emp-1", "2026-08-01") is None


@pytest.mark.asyncio
async def test_cross_tenant_employee_profile_access_is_blocked(monkeypatch):
    from routers import statutory_profiles as routes

    monkeypatch.setattr(routes, "db", SimpleNamespace(
        employees=Collection([{"id": "emp-1", "org_id": "org-2"}]),
        employment_statutory_profiles=Collection()))
    actor = Context({"id": "admin"}, "org-1", "COMPANY_ADMIN")
    with pytest.raises(HTTPException) as exc:
        await routes.list_employee_profiles("emp-1", actor)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_manager_cannot_read_or_modify_statutory_profiles():
    manager = Context({"id": "manager"}, "org-1", "MANAGER")
    assert not has_permission("MANAGER", "compliance.view")
    assert not has_permission("MANAGER", "compliance.manage")
    with pytest.raises(HTTPException) as exc:
        await require_perm("compliance.manage")(manager)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_employee_cannot_modify_establishment_coverage():
    employee = Context({"id": "employee"}, "org-1", "EMPLOYEE")
    assert not has_permission("EMPLOYEE", "settings.manage")
    with pytest.raises(HTTPException) as exc:
        await require_perm("settings.manage")(employee)
    assert exc.value.status_code == 403
    with pytest.raises(Exception):
        EmploymentStatutoryProfileIn.model_validate({
            "effective_from": "2026-08-01", "pf_covered": True,
        })


@pytest.mark.asyncio
async def test_profile_context_feeds_pf_and_state_rules_for_effective_period(monkeypatch):
    from services import employment_statutory_profiles as profile_service

    effective = profile_doc(
        "profile-1", "2026-01-01", work_location_id="loc-1", establishment_id="est-1",
        work_state="KA", pf_applicable=True, epf_membership_status="member",
        eps_applicable=True, membership_effective_from="2020-03-01",
        pf_on_higher_wages=False, pt_applicable=True, pt_employee_category="standard",
        lwf_applicable=True,
    )
    establishment = {"id": "est-1", "org_id": "org-1", "effective_from": "2025-01-01",
                     "pf_covered": True, "lwf_covered": True}
    monkeypatch.setattr(profile_service, "db", SimpleNamespace(
        employment_statutory_profiles=Collection([effective]),
        locations=Collection([{"id": "loc-1", "org_id": "org-1", "state": "KA"}]),
        statutory_establishments=Collection([establishment])))
    calls = []

    async def fake_get_rule(org_id, jurisdiction, rule_type, on_date, state=None, allow_unverified=False):
        calls.append((rule_type, on_date, state))
        return {"id": rule_type, "verified": True}

    monkeypatch.setattr(payroll_service, "get_rule", fake_get_rule)
    result = await payroll_service.resolve_employee_rules(
        {"id": "org-1", "jurisdiction": "IN", "payroll_settings": {}},
        {"id": "emp-1", "org_id": "org-1", "state": "RJ", "pf_applicable": False,
         "esi_applicable": False, "pt_applicable": False, "lwf_applicable": False, "tax_regime": "new"},
        "2026-08-01")
    overrides = result["__employee_overrides"]
    assert overrides["pf_applicable"] is True
    assert overrides["pf_on_higher_wages"] is False
    assert overrides["state"] == "KA"
    assert overrides["pt_employee_category"] == "standard"
    assert calls == [
        ("income_tax_new_regime", "2026-08-01", None),
        ("provident_fund", "2026-08-01", None),
        ("professional_tax", "2026-08-01", "KA"),
        ("lwf", "2026-08-01", "KA"),
    ]


@pytest.mark.asyncio
async def test_explicit_pf_applicability_without_establishment_coverage_fails_closed(monkeypatch):
    from services import employment_statutory_profiles as profile_service

    current = profile_doc("profile-1", "2026-01-01", pf_applicable=True)
    monkeypatch.setattr(profile_service, "db", SimpleNamespace(
        employment_statutory_profiles=Collection([current]), locations=Collection(),
        statutory_establishments=Collection()))

    async def fake_get_rule(*args, **kwargs):
        return {"id": args[2], "verified": True}

    monkeypatch.setattr(payroll_service, "get_rule", fake_get_rule)
    with pytest.raises(RuleUnavailable, match="PF establishment coverage"):
        await payroll_service.resolve_employee_rules(
            {"id": "org-1", "jurisdiction": "IN", "payroll_settings": {}},
            {"id": "emp-1", "state": "KA", "pf_applicable": True, "tax_regime": "new"},
            "2026-08-01")


@pytest.mark.asyncio
async def test_establishment_references_are_tenant_scoped(monkeypatch):
    monkeypatch.setattr(profiles, "db", SimpleNamespace(
        locations=Collection([{"id": "loc-1", "org_id": "org-2"}]),
        statutory_establishments=Collection()))
    with pytest.raises(HTTPException) as exc:
        await profiles.validate_org_references("org-1", "loc-1", None)
    assert exc.value.status_code == 422


def test_establishment_and_profile_date_ranges_are_validated():
    with pytest.raises(Exception):
        StatutoryEstablishmentIn(name="Plant", effective_from="2026-08-02", effective_to="2026-08-01")
    with pytest.raises(Exception):
        EmploymentStatutoryProfileIn(effective_from="2026-08-02", effective_to="2026-08-01")
