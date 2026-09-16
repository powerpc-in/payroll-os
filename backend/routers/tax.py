"""Tax declarations, regime comparison and versioned statutory-rule inspection."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib.auth import Context, get_ctx, new_id, require_perm
from lib.db import db
from lib.dates import today_iso
from services import payroll_engine, tax_engine
from services.rules import RuleUnavailable, get_rule, rule_ref

router = APIRouter(prefix="/v1/tax", tags=["Tax"])


class DeclarationsIn(BaseModel):
    deduction_80c: float = 0
    deduction_80d: float = 0
    annual_rent_paid: float = 0
    metro: bool = False
    other_income: float = 0


async def _employee_for(ctx: Context, employee_id: str | None) -> dict:
    if ctx.role == "EMPLOYEE" or not employee_id:
        eid = ctx.user.get("employee_id")
        if not eid:
            raise HTTPException(status_code=400, detail="Login is not linked to an employee record")
        employee_id = eid
    emp = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    return emp


async def _comparison(org: dict, emp: dict, period: str | None) -> dict:
    period = period or today_iso()[:7]
    on_date = f"{period}-01"
    _, months_elapsed, fy_label = payroll_engine.fy_of_period(period)
    assignment = await db.salary_assignments.find_one(
        {"org_id": org["id"], "employee_id": emp["id"], "active": True})
    if not assignment:
        raise HTTPException(status_code=400, detail="No active salary assignment for this employee")
    structure = await db.salary_structures.find_one({"id": assignment["structure_id"]})
    if not structure:
        raise HTTPException(status_code=400, detail="Assigned salary structure missing")
    comps = payroll_engine.monthly_components(structure, assignment["gross_monthly"])
    basic_monthly = next((c["monthly"] for c in comps if c["code"] == "BASIC"), 0)
    hra_monthly = next((c["monthly"] for c in comps if c["code"] == "HRA"), 0)
    taxable_monthly = sum(c["monthly"] for c in comps if c["taxable"])

    decl = await db.tax_declarations.find_one(
        {"org_id": org["id"], "employee_id": emp["id"]}, {"_id": 0}) or {}
    allow = org.get("payroll_settings", {}).get("accept_unverified_statutory_values", False)
    jur = org.get("jurisdiction", "IN")

    out = {"employee_id": emp["id"], "fy": fy_label, "months_elapsed_in_fy": months_elapsed,
           "regimes": {}, "unverified": False, "error": None}
    try:
        for regime in ("old", "new"):
            rule = await get_rule(org["id"], jur, f"income_tax_{regime}_regime", on_date, None, allow)
            projection = tax_engine.project_annual_taxable(
                taxable_monthly, 12, regime, rule["params"], decl, basic_monthly, hra_monthly)
            tax = tax_engine.compute_income_tax(projection["taxable"], rule["params"])
            monthly_tds = round(tax["total_annual_tax"] / 12, 2)
            out["regimes"][regime] = {
                "rule_ref": rule_ref(rule),
                "lines": projection["lines"],
                "taxable_income": projection["taxable"],
                "tax_before_rebate": tax["tax_before_rebate"],
                "rebate_87a": tax["rebate_87a"],
                "surcharge": tax["surcharge"],
                "health_education_cess": tax["health_education_cess"],
                "annual_tax": tax["total_annual_tax"],
                "monthly_tds": monthly_tds,
                "slab_lines": tax_engine.slab_explanation(projection["taxable"], rule["params"]["slabs"]),
            }
        old_t = out["regimes"]["old"]["annual_tax"]
        new_t = out["regimes"]["new"]["annual_tax"]
        out["difference"] = {"old_minus_new": round(old_t - new_t, 2),
                             "cheaper_regime": ("old" if old_t < new_t else "new" if new_t < old_t else "equal")}
        out["unverified"] = any(not r["verified"] for r in
                                (out["regimes"]["old"]["rule_ref"], out["regimes"]["new"]["rule_ref"]))
    except RuleUnavailable as exc:
        out["error"] = str(exc)
    return out


@router.get("/compare")
async def compare(employee_id: str | None = None, period: str | None = None,
                  ctx: Context = Depends(require_perm("tax.view"))):
    emp = await _employee_for(ctx, employee_id)
    org = await db.organisations.find_one({"id": ctx.org_id})
    return await _comparison(org, emp, period)


class CompareSelfOut(dict):
    pass


@router.get("/declarations")
async def get_declarations(employee_id: str | None = None, ctx: Context = Depends(get_ctx)):
    emp = await _employee_for(ctx, employee_id)
    if ctx.role == "EMPLOYEE" and emp.get("user_id") != ctx.user_id and not ctx.can("tax.view"):
        raise HTTPException(status_code=403, detail="Not your profile")
    doc = await db.tax_declarations.find_one({"org_id": ctx.org_id, "employee_id": emp["id"]},
                                             {"_id": 0, "org_id": 0})
    return doc or {"deduction_80c": 0, "deduction_80d": 0, "annual_rent_paid": 0,
                   "metro": False, "other_income": 0}


@router.put("/declarations")
async def put_declarations(input: DeclarationsIn, employee_id: str | None = None,
                           ctx: Context = Depends(get_ctx)):
    emp = await _employee_for(ctx, employee_id)
    if ctx.role == "EMPLOYEE" and emp.get("user_id") != ctx.user_id and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Not your profile")
    existing = await db.tax_declarations.find_one({"org_id": ctx.org_id, "employee_id": emp["id"]})
    if existing:
        await db.tax_declarations.update_one({"id": existing["id"]}, {"$set": input.model_dump()})
    else:
        await db.tax_declarations.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "employee_id": emp["id"], **input.model_dump(),
        })
    doc = await db.tax_declarations.find_one({"org_id": ctx.org_id, "employee_id": emp["id"]},
                                             {"_id": 0, "org_id": 0})
    return doc
