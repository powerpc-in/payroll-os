"""Employee master — full profiles with tenant isolation and sensitive-field masking."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from lib.team_scope import manager_team_ids, require_manager_team_member
from services.payroll_engine import mask_account, mask_pan
from services.statutory_profile_models import EmploymentStatutoryProfileIn
from services.employment_statutory_profiles import insert_profile, validate_org_references
from services.tax_year_profiles import TaxYearProfileIn, upsert_tax_profile

router = APIRouter(prefix="/v1", tags=["Employees"])

SENSITIVE = ["pan", "uan", "pf_number", "esi_number", "bank_account", "aadhaar"]
EMPLOYEE_FIELDS = [
    "name", "date_of_birth", "gender", "marital_status", "personal_email", "work_email",
    "phone", "address", "city", "state", "pin", "joining_date", "confirmation_date",
    "employment_type", "department_id", "department_name", "designation", "grade",
    "location_name", "reporting_manager_id", "cost_centre", "status", "exit_date",
    "exit_reason", "pan", "uan", "pf_number", "pf_applicable", "esi_number",
    "esi_applicable", "pt_applicable", "lwf_applicable", "tax_regime", "bank_name",
    "bank_account", "ifsc", "account_holder", "emergency_contact_name",
    "emergency_contact_phone", "aadhaar",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


def mask(doc: dict, reveal: bool) -> dict:
    if reveal:
        return doc
    for f in SENSITIVE:
        v = doc.get(f)
        if not v:
            continue
        if f == "pan":
            doc[f] = mask_pan(v)
        elif f in ("bank_account", "aadhaar"):
            doc[f] = mask_account(v)
        else:
            doc[f] = "•••" + v[-3:] if len(v) > 3 else "•••"
    return doc


class EmployeeIn(BaseModel):
    name: str
    date_of_birth: str | None = None
    gender: str | None = None
    marital_status: str | None = None
    personal_email: str | None = None
    work_email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pin: str | None = None
    joining_date: str
    confirmation_date: str | None = None
    employment_type: str = "full_time"
    department_name: str | None = None
    designation: str | None = None
    grade: str | None = None
    location_name: str | None = None
    reporting_manager_id: str | None = None
    cost_centre: str | None = None
    status: str = "active"
    pan: str | None = None
    uan: str | None = None
    pf_number: str | None = None
    pf_applicable: bool = True
    esi_number: str | None = None
    esi_applicable: bool = True
    pt_applicable: bool = True
    lwf_applicable: bool = True
    tax_regime: str = "new"
    bank_name: str | None = None
    bank_account: str | None = None
    ifsc: str | None = None
    account_holder: str | None = None
    statutory_profile: EmploymentStatutoryProfileIn | None = None
    tax_year_profile: TaxYearProfileIn | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


async def _resolve_department(org_id: str, name: str | None) -> str:
    if not name or not name.strip():
        return ""
    name = name.strip()
    existing = await db.departments.find_one({"org_id": org_id, "name": name})
    if existing:
        return existing["id"]
    dept_id = new_id()
    await db.departments.insert_one({"id": dept_id, "org_id": org_id, "name": name, "created_at": now()})
    return dept_id


@router.get("/employees")
async def list_employees(
    ctx: Context = Depends(require_perm("employees.view")),
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
    q: str | None = None, department_id: str | None = None,
    location_name: str | None = None, status: str | None = None,
    manager_id: str | None = None, reveal: bool = False,
):
    query: dict = {"org_id": ctx.org_id}
    if ctx.role == "MANAGER":
        query["id"] = {"$in": await manager_team_ids(ctx)}
    elif manager_id:
        query["reporting_manager_id"] = manager_id
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"employee_code": {"$regex": q, "$options": "i"}},
            {"work_email": {"$regex": q, "$options": "i"}},
        ]
    if department_id:
        query["department_id"] = department_id
    if location_name:
        query["location_name"] = location_name
    if status:
        query["status"] = status

    total = await db.employees.count_documents(query)
    docs = await db.employees.find(query).sort("created_at", -1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit + 1)
    emp_ids = [d["id"] for d in docs]
    gross_by_emp = {}
    if ctx.can("salary.view"):
        assignments = await db.salary_assignments.find(
            {"org_id": ctx.org_id, "active": True, "employee_id": {"$in": emp_ids}}).to_list(len(emp_ids) + 1)
        gross_by_emp = {a["employee_id"]: a["gross_monthly"] for a in assignments}
    items = []
    for d in docs:
        d.pop("_id", None)
        if ctx.can("salary.view"):
            d["gross_monthly"] = gross_by_emp.get(d["id"])
        items.append(mask(d, reveal and ctx.can("employees.view_sensitive")))
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.post("/employees")
async def create_employee(input: EmployeeIn, ctx: Context = Depends(require_perm("employees.create"))):
    if input.statutory_profile and not ctx.can("compliance.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: compliance.manage")
    if input.tax_year_profile and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    if input.statutory_profile:
        await validate_org_references(ctx.org_id, input.statutory_profile.work_location_id,
                                      input.statutory_profile.establishment_id)
    seq = await db.employees.count_documents({"org_id": ctx.org_id})
    dept_id = await _resolve_department(ctx.org_id, input.department_name)
    doc = input.model_dump(exclude={"statutory_profile", "tax_year_profile"})
    doc.update({
        "id": new_id(), "org_id": ctx.org_id, "employee_code": f"EMP-{seq + 1:04d}",
        "department_id": dept_id, "user_id": None, "created_at": now(),
    })
    await db.employees.insert_one(doc)
    profile_doc = None
    if input.statutory_profile:
        profile_doc = await insert_profile(ctx.org_id, doc["id"], input.statutory_profile)
    tax_profile_doc = None
    if input.tax_year_profile:
        tax_profile_doc = await upsert_tax_profile(ctx.org_id, doc["id"], input.tax_year_profile, ctx.user)
    doc.pop("_id", None)
    await emit(ctx.org_id, "employee.created", actor=ctx.user, entity="employee", entity_id=doc["id"],
               summary=f"Employee {input.name} ({doc['employee_code']}) created",
               data={"employee_id": doc["id"], "name": input.name})
    response = mask(doc, False)
    if profile_doc and ctx.can("compliance.view"):
        response["statutory_profile"] = profile_doc
    if tax_profile_doc and ctx.can("tax.view"):
        response["tax_year_profile"] = {k: v for k, v in tax_profile_doc.items() if k != "org_id"}
    return response


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, ctx: Context = Depends(require_perm("employees.view")),
                       reveal: bool = False):
    doc = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Employee not found")
    if ctx.role == "MANAGER":
        await require_manager_team_member(ctx, employee_id)
    assignments = []
    structures = {}
    if ctx.can("salary.view"):
        assignments = await db.salary_assignments.find(
            {"employee_id": employee_id, "org_id": ctx.org_id}, {"_id": 0}).sort("created_at", -1).to_list(10)
        for a in assignments:
            if a["structure_id"] not in structures:
                s = await db.salary_structures.find_one(
                    {"id": a["structure_id"], "org_id": ctx.org_id}, {"_id": 0})
                if s:
                    structures[a["structure_id"]] = s
    response = {"employee": mask(doc, reveal and ctx.can("employees.view_sensitive")),
                "assignments": assignments, "structures": list(structures.values())}
    profile_collection = getattr(db, "employment_statutory_profiles", None)
    if ctx.can("compliance.view") and profile_collection is not None:
        response["statutory_profiles"] = await profile_collection.find(
            {"org_id": ctx.org_id, "employee_id": employee_id}, {"_id": 0}
        ).sort([("effective_from", 1), ("created_at", 1), ("id", 1)]).to_list(500)
    if ctx.can("tax.view") and getattr(db, "tax_year_profiles", None) is not None:
        response["tax_year_profiles"] = await db.tax_year_profiles.find(
            {"org_id": ctx.org_id, "employee_id": employee_id}, {"_id": 0, "org_id": 0}
        ).sort([("financial_year", 1), ("updated_at", 1), ("id", 1)]).to_list(100)
    return response


@router.put("/employees/{employee_id}")
async def update_employee(employee_id: str, input: EmployeeIn,
                          ctx: Context = Depends(require_perm("employees.edit"))):
    if input.statutory_profile and not ctx.can("compliance.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: compliance.manage")
    if input.tax_year_profile and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    if input.statutory_profile:
        await validate_org_references(ctx.org_id, input.statutory_profile.work_location_id,
                                      input.statutory_profile.establishment_id)
    old = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id})
    if not old:
        raise HTTPException(status_code=404, detail="Employee not found")
    updates = input.model_dump(exclude={"statutory_profile", "tax_year_profile"})
    updates["department_id"] = await _resolve_department(ctx.org_id, input.department_name)
    changed = {k: v for k, v in updates.items() if old.get(k) != v}
    if changed:
        await db.employees.update_one({"id": employee_id, "org_id": ctx.org_id}, {"$set": changed})
        await emit(ctx.org_id, "employee.updated", actor=ctx.user, entity="employee",
                   entity_id=employee_id, old={k: old.get(k) for k in changed}, new=changed,
                   summary=f"Employee {old['name']} updated ({', '.join(list(changed)[:5])})")
    profile_doc = None
    if input.statutory_profile:
        profile_doc = await insert_profile(ctx.org_id, employee_id, input.statutory_profile)
    tax_profile_doc = None
    if input.tax_year_profile:
        tax_profile_doc = await upsert_tax_profile(ctx.org_id, employee_id, input.tax_year_profile, ctx.user)
    doc = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id}, {"_id": 0})
    response = mask(doc, False)
    if profile_doc and ctx.can("compliance.view"):
        response["statutory_profile"] = profile_doc
    if tax_profile_doc and ctx.can("tax.view"):
        response["tax_year_profile"] = {k: v for k, v in tax_profile_doc.items() if k != "org_id"}
    return response


@router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, ctx: Context = Depends(require_perm("employees.delete"))):
    old = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id})
    if not old:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.employees.delete_one({"id": employee_id, "org_id": ctx.org_id})
    await db.salary_assignments.update_many(
        {"employee_id": employee_id, "org_id": ctx.org_id}, {"$set": {"active": False}})
    await emit(ctx.org_id, "employee.terminated", actor=ctx.user, entity="employee",
               entity_id=employee_id, old={"name": old["name"]},
               summary=f"Employee {old['name']} deleted")
    return {"ok": True}


class ExitIn(BaseModel):
    exit_date: str
    exit_reason: str | None = None


@router.post("/employees/{employee_id}/exit")
async def exit_employee(employee_id: str, input: ExitIn,
                        ctx: Context = Depends(require_perm("employees.edit"))):
    old = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id})
    if not old:
        raise HTTPException(status_code=404, detail="Employee not found")
    await db.employees.update_one({"id": employee_id, "org_id": ctx.org_id}, {
        "$set": {"status": "exited", "exit_date": input.exit_date, "exit_reason": input.exit_reason},
    })
    await emit(ctx.org_id, "employee.terminated", actor=ctx.user, entity="employee",
               entity_id=employee_id, old={"status": old.get("status")},
               new={"status": "exited", "exit_date": input.exit_date},
               summary=f"Employee {old['name']} exited ({input.exit_date})")
    return {"ok": True}
