"""Tax-year-scoped employee tax profiles and declarations."""

from datetime import date, datetime, timezone
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from lib.auth import new_id
from lib.db import db
from lib.events import emit
from services import payroll_engine
from services.rules import RuleUnavailable

TaxRegime = Literal["old", "new"]
TaxResidency = Literal["resident_ordinary", "resident_not_ordinary", "non_resident"]


def financial_year_key(period: str) -> str:
    start, _, _ = payroll_engine.fy_of_period(period)
    return f"{start}-{(start + 1) % 100:02d}"


def fy_bounds(financial_year: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-\d{2}", financial_year):
        raise ValueError("financial_year must use YYYY-YY format")
    start_year = int(financial_year[:4])
    if int(financial_year[-2:]) != (start_year + 1) % 100:
        raise ValueError("financial_year must identify consecutive April-to-March years")
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


class TaxYearProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    financial_year: str
    tax_regime: TaxRegime
    tax_residency_status: TaxResidency | None = None

    @model_validator(mode="after")
    def valid_fy(self):
        fy_bounds(self.financial_year)
        return self


class TaxYearDeclarationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deduction_80c: float = Field(default=0, ge=0)
    deduction_80d: float = Field(default=0, ge=0)
    annual_rent_paid: float = Field(default=0, ge=0)
    other_income: float = Field(default=0, ge=0)
    rent_period_start: date | None = None
    rent_period_end: date | None = None
    residence_city: str | None = None
    residence_location: str | None = None
    metro: bool | None = None

    @model_validator(mode="after")
    def valid_hra_context(self):
        if bool(self.rent_period_start) != bool(self.rent_period_end):
            raise ValueError("rent_period_start and rent_period_end must be supplied together")
        if self.rent_period_start and self.rent_period_end and self.rent_period_end < self.rent_period_start:
            raise ValueError("rent_period_end must be on or after rent_period_start")
        has_residence = bool(self.residence_city or self.residence_location)
        if self.metro is not None and not has_residence:
            raise ValueError("metro classification requires a declared residence city or location")
        if self.annual_rent_paid > 0:
            if not (self.rent_period_start and self.rent_period_end):
                raise ValueError("rent payment period is required when annual rent is declared")
            if not has_residence:
                raise ValueError("residence city or location is required when annual rent is declared")
            if self.metro is None:
                raise ValueError("metro classification must be declared for the residence")
        return self


def select_tax_year_profile(profiles: list[dict], org_id: str, employee_id: str,
                            financial_year: str) -> dict | None:
    matching = [p for p in profiles if p.get("org_id") == org_id
                and p.get("employee_id") == employee_id
                and p.get("financial_year") == financial_year]
    if not matching:
        return None
    return max(matching, key=lambda p: (str(p.get("updated_at") or ""),
                                        str(p.get("created_at") or ""), str(p.get("id") or "")))


async def upsert_tax_profile(org_id: str, employee_id: str, input: TaxYearProfileIn,
                             actor: dict) -> dict:
    now = datetime.now(timezone.utc)
    query = {"org_id": org_id, "employee_id": employee_id,
             "financial_year": input.financial_year}
    fields = input.model_dump()
    existing = await db.tax_year_profiles.find_one(query, {"_id": 0})
    if existing:
        await db.tax_year_profiles.update_one(
            {"id": existing["id"], "org_id": org_id},
            {"$set": {**fields, "updated_at": now, "updated_by": actor.get("id") or actor.get("email")}})
    else:
        await db.tax_year_profiles.insert_one({
            "id": new_id(), **query, **fields, "created_at": now,
            "created_by": actor.get("id") or actor.get("email"), "updated_at": now,
            "updated_by": actor.get("id") or actor.get("email"),
        })
    doc = await db.tax_year_profiles.find_one(query, {"_id": 0})
    await emit(org_id, "tax.profile_updated", actor=actor, entity="tax_year_profile",
               entity_id=doc["id"], summary=f"Tax profile updated for {input.financial_year}",
               data={"employee_id": employee_id, "financial_year": input.financial_year})
    return doc


async def upsert_declarations(org_id: str, employee_id: str, financial_year: str,
                              input: TaxYearDeclarationsIn, actor: dict) -> dict:
    start, end = fy_bounds(financial_year)
    values = input.model_dump(mode="json")
    if values.get("rent_period_start"):
        rent_start = date.fromisoformat(values["rent_period_start"])
        rent_end = date.fromisoformat(values["rent_period_end"])
        if rent_start < start or rent_end > end:
            raise HTTPException(status_code=422, detail="Rent period must fall within the selected financial year")
    query = {"org_id": org_id, "employee_id": employee_id,
             "financial_year": financial_year}
    now = datetime.now(timezone.utc)
    existing = await db.tax_year_declarations.find_one(query, {"_id": 0})
    actor_ref = actor.get("id") or actor.get("email")
    if existing:
        await db.tax_year_declarations.update_one(
            {"id": existing["id"], "org_id": org_id},
            {"$set": {**values, "updated_at": now, "updated_by": actor_ref}})
    else:
        await db.tax_year_declarations.insert_one({
            "id": new_id(), **query, **values, "created_at": now,
            "created_by": actor_ref, "updated_at": now, "updated_by": actor_ref,
        })
    doc = await db.tax_year_declarations.find_one(query, {"_id": 0})
    await emit(org_id, "tax.declarations_updated", actor=actor, entity="tax_declaration",
               entity_id=doc["id"], summary=f"Tax declarations updated for {financial_year}",
               data={"employee_id": employee_id, "financial_year": financial_year})
    return doc


async def resolve_tax_year_context(org_id: str, employee: dict, period: str) -> dict:
    fy = financial_year_key(period)
    query = {"org_id": org_id, "employee_id": employee["id"], "financial_year": fy}
    profile_docs = await db.tax_year_profiles.find(query, {"_id": 0}).to_list(20)
    profile = select_tax_year_profile(profile_docs, org_id, employee["id"], fy)
    declaration = await db.tax_year_declarations.find_one(query, {"_id": 0}) or {}
    return {
        "financial_year": fy,
        "profile": profile,
        "employee_overrides": {
            "tax_regime": profile.get("tax_regime") if profile else (employee.get("tax_regime") or "new"),
            "tax_residency_status": profile.get("tax_residency_status") if profile else None,
        },
        "declarations": declaration,
    }


def require_supported_residency(rule: dict, tax_residency_status: str | None,
                                jurisdiction: str, state: str | None = None) -> None:
    """Fail closed when the existing formula would apply a resident-only rebate."""
    params = rule.get("params") or {}
    requires_residency = bool(params.get("requires_tax_residency") or params.get("rebate"))
    if not requires_residency:
        return
    if tax_residency_status is None:
        raise RuleUnavailable(rule.get("rule_type", "income_tax"), jurisdiction, state,
                              "Tax residency status is required by this tax rule")
    if tax_residency_status == "non_resident":
        raise RuleUnavailable(rule.get("rule_type", "income_tax"), jurisdiction, state,
                              "Current tax engine cannot safely apply resident-only rebate treatment to a non-resident")
    if tax_residency_status == "resident_not_ordinary":
        raise RuleUnavailable(rule.get("rule_type", "income_tax"), jurisdiction, state,
                              "Current tax rule does not encode rebate eligibility for a resident not ordinarily resident")
