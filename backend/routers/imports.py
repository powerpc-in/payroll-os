"""CSV import center — employees and salary assignments, with validation,
error report and clearly-identified partial imports (spec §29)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from services.statutory_profile_models import EmploymentStatutoryProfileIn
from services.employment_statutory_profiles import insert_profile, validate_org_references
from services.tax_year_profiles import TaxYearProfileIn, upsert_tax_profile

router = APIRouter(prefix="/v1/imports", tags=["Imports"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class EmployeeRow(BaseModel):
    name: str
    joining_date: str
    gross_monthly: float = Field(gt=0)
    email: str | None = None
    phone: str | None = None
    department: str | None = None
    designation: str | None = None
    state: str | None = None
    tax_regime: str = "new"
    pf_applicable: bool = True
    esi_applicable: bool = True
    statutory_profile: EmploymentStatutoryProfileIn | None = None
    tax_year_profile: TaxYearProfileIn | None = None


class EmployeeImport(BaseModel):
    rows: list[EmployeeRow]


@router.get("/employees/template")
async def employee_template(ctx: Context = Depends(require_perm("imports.manage"))):
    csv_text = (
        "name,joining_date,gross_monthly,email,phone,department,designation,state,tax_regime,pf_applicable,esi_applicable\n"
        "Fictional Name,2026-01-01,50000,name@example.com,9000000000,Engineering,Engineer,KA,new,true,true\n"
    )
    return StreamingResponse(iter([csv_text]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="employee-import-template.csv"'})


@router.post("/employees")
async def import_employees(input: EmployeeImport, ctx: Context = Depends(require_perm("imports.manage"))):
    if any(row.statutory_profile for row in input.rows) and not ctx.can("compliance.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: compliance.manage")
    if any(row.tax_year_profile for row in input.rows) and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    org = await db.organisations.find_one({"id": ctx.org_id})
    structure = await db.salary_structures.find_one({"org_id": ctx.org_id})
    if not structure:
        return {"imported": 0, "errors": [{"row": 0, "errors": ["Create a salary structure before importing employees"]}],
                "total": len(input.rows)}
    errors: list[dict] = []
    imported = 0
    seq = await db.employees.count_documents({"org_id": ctx.org_id})
    from datetime import date
    for i, row in enumerate(input.rows):
        row_errors: list[str] = []
        try:
            date.fromisoformat(row.joining_date)
        except ValueError:
            row_errors.append("joining_date must be YYYY-MM-DD")
        if row.tax_regime not in ("old", "new"):
            row_errors.append("tax_regime must be 'old' or 'new'")
        if row.statutory_profile:
            try:
                await validate_org_references(ctx.org_id, row.statutory_profile.work_location_id,
                                              row.statutory_profile.establishment_id)
            except HTTPException as exc:
                row_errors.append(str(exc.detail))
        if row_errors:
            errors.append({"row": i + 1, "name": row.name, "errors": row_errors})
            continue
        seq += 1
        dept_name = (row.department or "").strip()
        dept_id = ""
        if dept_name:
            existing = await db.departments.find_one({"org_id": ctx.org_id, "name": dept_name})
            dept_id = existing["id"] if existing else new_id()
            if not existing:
                await db.departments.insert_one({"id": dept_id, "org_id": ctx.org_id,
                                                 "name": dept_name, "created_at": now()})
        emp_id = new_id()
        await db.employees.insert_one({
            "id": emp_id, "org_id": ctx.org_id, "employee_code": f"EMP-{seq:04d}",
            "name": row.name, "work_email": row.email, "personal_email": None,
            "phone": row.phone, "date_of_birth": None, "gender": None, "marital_status": None,
            "address": "", "city": "", "state": row.state or org.get("state") or "KA", "pin": "",
            "joining_date": row.joining_date, "confirmation_date": None,
            "employment_type": "full_time", "department_id": dept_id, "department_name": dept_name,
            "designation": row.designation or "", "grade": "", "location_name": "",
            "reporting_manager_id": None, "cost_centre": "", "status": "active",
            "exit_date": None, "exit_reason": None,
            "pan": None, "uan": None, "pf_number": None, "pf_applicable": row.pf_applicable,
            "esi_number": None, "esi_applicable": row.esi_applicable,
            "pt_applicable": True, "lwf_applicable": True, "tax_regime": row.tax_regime,
            "bank_name": None, "bank_account": None, "ifsc": None, "account_holder": None,
            "emergency_contact_name": None, "emergency_contact_phone": None,
            "user_id": None, "created_at": now(),
        })
        if row.statutory_profile:
            await insert_profile(ctx.org_id, emp_id, row.statutory_profile)
        if row.tax_year_profile:
            await upsert_tax_profile(ctx.org_id, emp_id, row.tax_year_profile, ctx.user)
        await db.salary_assignments.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "employee_id": emp_id,
            "structure_id": structure["id"], "gross_monthly": row.gross_monthly,
            "effective_from": row.joining_date, "active": True, "created_at": now(),
        })
        lts = await db.leave_types.find({"org_id": ctx.org_id}).to_list(20)
        for lt in lts:
            await db.leave_balances.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "employee_id": emp_id,
                "leave_type_id": lt["id"], "leave_code": lt["code"],
                "granted": lt["annual_quota"], "used": 0, "year": row.joining_date[:4],
            })
        imported += 1
    await emit(ctx.org_id, "employee.imported", actor=ctx.user, entity="employee",
               summary=f"Employee import: {imported} imported, {len(errors)} rejected")
    return {"imported": imported, "errors": errors, "total": len(input.rows)}


class SalaryRow(BaseModel):
    employee_code: str
    gross_monthly: float = Field(gt=0)


class SalaryImport(BaseModel):
    rows: list[SalaryRow]


@router.get("/salaries/template")
async def salary_template(ctx: Context = Depends(require_perm("imports.manage"))):
    csv_text = "employee_code,gross_monthly\nEMP-0001,50000\n"
    return StreamingResponse(iter([csv_text]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="salary-import-template.csv"'})


@router.post("/salaries")
async def import_salaries(input: SalaryImport, ctx: Context = Depends(require_perm("imports.manage"))):
    structure = await db.salary_structures.find_one({"org_id": ctx.org_id})
    if not structure:
        return {"imported": 0, "errors": [{"row": 0, "errors": ["Create a salary structure first"]}],
                "total": len(input.rows)}
    errors: list[dict] = []
    imported = 0
    for i, row in enumerate(input.rows):
        emp = await db.employees.find_one(
            {"org_id": ctx.org_id, "employee_code": row.employee_code.strip().upper()})
        if not emp:
            errors.append({"row": i + 1, "errors": [f"Employee code {row.employee_code} not found"]})
            continue
        await db.salary_assignments.update_many(
            {"employee_id": emp["id"], "active": True},
            {"$set": {"active": False, "superseded_at": now()}})
        await db.salary_assignments.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "employee_id": emp["id"],
            "structure_id": structure["id"], "gross_monthly": row.gross_monthly,
            "effective_from": now().date().isoformat(), "active": True, "created_at": now(),
        })
        await emit(ctx.org_id, "salary.updated", actor=ctx.user, entity="salary_assignment",
                   summary=f"Salary ₹{row.gross_monthly:,.0f}/month imported for {emp['name']}")
        imported += 1
    return {"imported": imported, "errors": errors, "total": len(input.rows)}
