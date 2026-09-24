"""Tenant-scoped, effective-dated employment and establishment statutory context."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from lib.auth import Context, new_id, require_perm
from lib.db import db
from services.employment_statutory_profiles import insert_profile, validate_org_references
from services.statutory_profile_models import EmploymentStatutoryProfileIn, StatutoryEstablishmentIn

router = APIRouter(prefix="/v1", tags=["Employment Statutory Profiles"])


def now():
    return datetime.now(timezone.utc)


@router.get("/employees/{employee_id}/statutory-profiles")
async def list_employee_profiles(employee_id: str,
                                ctx: Context = Depends(require_perm("compliance.view"))):
    if not await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Employee not found")
    return await db.employment_statutory_profiles.find(
        {"org_id": ctx.org_id, "employee_id": employee_id}, {"_id": 0}
    ).sort([("effective_from", 1), ("created_at", 1), ("id", 1)]).to_list(500)


@router.post("/employees/{employee_id}/statutory-profiles")
async def add_employee_profile(employee_id: str, profile: EmploymentStatutoryProfileIn,
                               ctx: Context = Depends(require_perm("compliance.manage"))):
    if not await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Employee not found")
    return await insert_profile(ctx.org_id, employee_id, profile)


@router.get("/compliance/establishments")
async def list_establishments(ctx: Context = Depends(require_perm("compliance.view"))):
    return await db.statutory_establishments.find(
        {"org_id": ctx.org_id}, {"_id": 0}
    ).sort([("name", 1), ("effective_from", 1), ("id", 1)]).to_list(500)


@router.post("/compliance/establishments")
async def add_establishment(establishment: StatutoryEstablishmentIn,
                            ctx: Context = Depends(require_perm("settings.manage"))):
    if establishment.location_id and not await db.locations.find_one(
            {"id": establishment.location_id, "org_id": ctx.org_id}, {"_id": 1}):
        raise HTTPException(status_code=422, detail="Work location not found in this organisation")
    doc = establishment.model_dump(mode="json")
    doc.update({"id": new_id(), "org_id": ctx.org_id, "created_at": now()})
    await db.statutory_establishments.insert_one(doc)
    doc.pop("_id", None)
    return doc
