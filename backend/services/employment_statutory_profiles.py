"""Effective-dated employee worksite and statutory applicability context."""

from datetime import date, datetime, timezone

from fastapi import HTTPException

from lib.auth import new_id
from lib.db import db
from services.rules import RuleUnavailable
from services.statutory_profile_models import EmploymentStatutoryProfileIn


def _date_key(value) -> str | None:
    if value is None:
        return None
    candidate = value.date().isoformat() if isinstance(value, datetime) else str(value)[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def select_effective_profile(profiles: list[dict], org_id: str, employee_id: str,
                             on_date: str) -> dict | None:
    """Choose the latest profile effective on the payroll date; ties are stable."""
    target = _date_key(on_date)
    if not target:
        return None
    valid = []
    for profile in profiles:
        if profile.get("org_id") != org_id or profile.get("employee_id") != employee_id:
            continue
        start = _date_key(profile.get("effective_from"))
        end = _date_key(profile.get("effective_to"))
        if not start or start > target or (profile.get("effective_to") and (not end or end < target)):
            continue
        valid.append(profile)
    if not valid:
        return None
    return max(valid, key=lambda p: (_date_key(p.get("effective_from")) or "",
                                    str(p.get("created_at") or ""), str(p.get("id") or "")))


async def validate_org_references(org_id: str, location_id: str | None,
                                  establishment_id: str | None,
                                  work_state: str | None = None) -> None:
    location = None
    if location_id and not await db.locations.find_one({"id": location_id, "org_id": org_id}):
        raise HTTPException(status_code=422, detail="Work location not found in this organisation")
    if location_id:
        location = await db.locations.find_one({"id": location_id, "org_id": org_id}, {"_id": 0})
        if work_state and location.get("state") and work_state != location["state"]:
            raise HTTPException(status_code=422, detail="Work state must match the linked work location")
    if establishment_id and not await db.statutory_establishments.find_one(
            {"id": establishment_id, "org_id": org_id}):
        raise HTTPException(status_code=422, detail="Establishment not found in this organisation")
    if establishment_id and location_id:
        establishment = await db.statutory_establishments.find_one(
            {"id": establishment_id, "org_id": org_id}, {"_id": 0})
        if establishment.get("location_id") and establishment["location_id"] != location_id:
            raise HTTPException(status_code=422, detail="Establishment is not linked to the selected work location")


async def insert_profile(org_id: str, employee_id: str,
                         profile: EmploymentStatutoryProfileIn) -> dict:
    await validate_org_references(org_id, profile.work_location_id, profile.establishment_id,
                                  profile.work_state)
    doc = profile.model_dump(mode="json")
    doc.update({"id": new_id(), "org_id": org_id, "employee_id": employee_id,
                "created_at": datetime.now(timezone.utc)})
    await db.employment_statutory_profiles.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def current_profile(org_id: str, employee_id: str, on_date: str) -> dict | None:
    profiles = await db.employment_statutory_profiles.find({
        "org_id": org_id, "employee_id": employee_id,
    }, {"_id": 0}).to_list(500)
    return select_effective_profile(profiles, org_id, employee_id, on_date)


async def resolve_context(org_id: str, employee: dict, on_date: str,
                          jurisdiction: str = "IN") -> tuple[dict | None, dict | None, dict | None]:
    """Return period profile and establishment; all lookups are tenant scoped."""
    profiles = await db.employment_statutory_profiles.find({
        "org_id": org_id, "employee_id": employee["id"],
    }, {"_id": 0}).to_list(500)
    profile = select_effective_profile(profiles, org_id, employee["id"], on_date)
    if not profile:
        # Legacy-only employees keep their historical applicability fields. Once an
        # employee has statutory profile history, however, an out-of-period profile
        # must not make those legacy PF fields an implicit membership fallback.
        if profiles and employee.get("pf_applicable"):
            raise RuleUnavailable("employment_profile", jurisdiction,
                                  employee.get("work_state") or employee.get("state"),
                                  "No effective statutory profile is available to establish PF membership for this payroll period")
        return None, None, None
    location = None
    if profile.get("work_location_id"):
        location = await db.locations.find_one({
            "id": profile["work_location_id"], "org_id": org_id,
        }, {"_id": 0})
        if not location:
            raise RuleUnavailable("employment_profile", jurisdiction, None,
                                  "Effective work location is unavailable for statutory resolution")
        if not location.get("state") and not profile.get("work_state"):
            raise RuleUnavailable("employment_profile", jurisdiction, None,
                                  "Effective work location has no state for statutory resolution")
    establishment = None
    if profile.get("establishment_id"):
        establishment = await db.statutory_establishments.find_one({
            "id": profile["establishment_id"], "org_id": org_id,
        }, {"_id": 0})
        if not establishment:
            raise RuleUnavailable("employment_profile", jurisdiction, None,
                                  "Effective establishment is unavailable for statutory resolution")
        start = _date_key(establishment.get("effective_from"))
        end = _date_key(establishment.get("effective_to"))
        if not start or start > on_date or (establishment.get("effective_to") and (not end or end < on_date)):
            raise RuleUnavailable("employment_profile", jurisdiction, None,
                                  "No establishment coverage profile is effective for this payroll period")
    return profile, location, establishment


def apply_context(employee: dict, profile: dict | None, location: dict | None,
                  establishment: dict | None) -> tuple[dict, str | None]:
    """Overlay only explicitly supplied values; legacy employee fields remain compatible."""
    resolved = dict(employee)
    if not profile:
        return resolved, employee.get("work_state") or employee.get("state")
    if profile.get("work_state"):
        resolved["work_state"] = profile["work_state"]
    elif location and location.get("state"):
        resolved["work_state"] = location["state"]
    elif employee.get("state"):
        resolved["work_state"] = employee["state"]
    if profile.get("pt_applicable") is not None:
        resolved["pt_applicable"] = profile["pt_applicable"]
    if profile.get("lwf_applicable") is not None:
        resolved["lwf_applicable"] = profile["lwf_applicable"]
    if profile.get("pt_employee_category") is not None:
        resolved["pt_employee_category"] = profile["pt_employee_category"]
    for field in ("pf_applicable", "pf_on_higher_wages"):
        if profile.get(field) is not None:
            resolved[field] = profile[field]
    if profile.get("epf_membership_status") == "not_member":
        resolved["pf_applicable"] = False
    elif profile.get("epf_membership_status") == "member":
        resolved["pf_applicable"] = True
    if establishment:
        if establishment.get("pf_covered") is False:
            resolved["pf_applicable"] = False
        if establishment.get("lwf_covered") is False:
            resolved["lwf_applicable"] = False
        if establishment.get("pf_scheme_category"):
            resolved["pf_scheme_category"] = establishment["pf_scheme_category"]
        if establishment.get("lwf_category"):
            resolved["lwf_category"] = establishment["lwf_category"]
    state = (location or {}).get("state") or profile.get("work_state") or employee.get("work_state") or employee.get("state")
    if state:
        # The existing payroll engine reads employee.state first for state levies.
        resolved["state"] = state
        resolved["work_state"] = state
    return resolved, state
