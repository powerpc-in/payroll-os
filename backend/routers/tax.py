"""Tax declarations, regime comparison and versioned statutory-rule inspection."""

from fastapi import APIRouter, Depends, HTTPException
from lib.auth import Context, get_ctx, require_perm
from lib.db import db
from lib.dates import today_iso
from services import payroll_engine, tax_engine
from services.rules import RuleUnavailable, get_rule, rule_ref
from services.tax_year_profiles import (
    TaxYearDeclarationsIn, TaxYearProfileIn, financial_year_key, fy_bounds,
    require_supported_residency, resolve_tax_year_context, upsert_declarations,
    upsert_tax_profile,
)

router = APIRouter(prefix="/v1/tax", tags=["Tax"])


DeclarationsIn = TaxYearDeclarationsIn


async def _employee_for(ctx: Context, employee_id: str | None) -> dict:
    if ctx.role == "EMPLOYEE":
        eid = ctx.user.get("employee_id")
        if not eid:
            raise HTTPException(status_code=400, detail="Login is not linked to an employee record")
        if employee_id and employee_id != eid:
            raise HTTPException(status_code=403, detail="Employees may access only their own tax declaration")
        employee_id = eid
    elif not employee_id:
        eid = ctx.user.get("employee_id")
        if not eid:
            raise HTTPException(status_code=422, detail="employee_id is required")
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
    structure = await db.salary_structures.find_one(
        {"id": assignment["structure_id"], "org_id": assignment["org_id"]})
    if not structure:
        raise HTTPException(status_code=400, detail="Assigned salary structure missing")
    comps = payroll_engine.monthly_components(structure, assignment["gross_monthly"])
    basic_monthly = next((c["monthly"] for c in comps if c["code"] == "BASIC"), 0)
    hra_monthly = next((c["monthly"] for c in comps if c["code"] == "HRA"), 0)
    taxable_monthly = sum(c["monthly"] for c in comps if c["taxable"])

    tax_context = await resolve_tax_year_context(org["id"], emp, period)
    decl = tax_context["declarations"]
    residency = tax_context["employee_overrides"]["tax_residency_status"]
    allow = org.get("payroll_settings", {}).get("accept_unverified_statutory_values", False)
    jur = org.get("jurisdiction", "IN")

    out = {"employee_id": emp["id"], "fy": fy_label, "months_elapsed_in_fy": months_elapsed,
           "regimes": {}, "unverified": False, "error": None}
    try:
        for regime in ("old", "new"):
            rule = await get_rule(org["id"], jur, f"income_tax_{regime}_regime", on_date, None, allow)
            require_supported_residency(rule, residency, jur)
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
async def get_declarations(employee_id: str | None = None, ctx: Context = Depends(get_ctx),
                           financial_year: str | None = None):
    if ctx.role != "EMPLOYEE" and not ctx.can("tax.view"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.view")
    emp = await _employee_for(ctx, employee_id)
    if ctx.role == "EMPLOYEE" and emp.get("user_id") != ctx.user_id:
        raise HTTPException(status_code=403, detail="Not your profile")
    fy = _resolve_fy(financial_year)
    doc = await db.tax_year_declarations.find_one(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "financial_year": fy},
        {"_id": 0, "org_id": 0})
    return doc or _empty_declarations(fy)


@router.put("/declarations")
async def put_declarations(input: DeclarationsIn, employee_id: str | None = None,
                           ctx: Context = Depends(get_ctx), financial_year: str | None = None):
    if ctx.role != "EMPLOYEE" and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    emp = await _employee_for(ctx, employee_id)
    if ctx.role == "EMPLOYEE" and emp.get("user_id") != ctx.user_id:
        raise HTTPException(status_code=403, detail="Not your profile")
    fy = _resolve_fy(financial_year)
    doc = await upsert_declarations(ctx.org_id, emp["id"], fy, input, ctx.user)
    doc.pop("org_id", None)
    return doc


def _resolve_fy(value: str | None) -> str:
    fy = value or financial_year_key(today_iso()[:7])
    try:
        fy_bounds(fy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return fy


def _empty_declarations(financial_year: str) -> dict:
    return {"financial_year": financial_year, "deduction_80c": 0, "deduction_80d": 0,
            "annual_rent_paid": 0, "rent_period_start": None, "rent_period_end": None,
            "residence_city": None, "residence_location": None, "metro": None,
            "other_income": 0}


@router.get("/profiles")
async def get_tax_profile(employee_id: str | None = None, financial_year: str | None = None,
                          ctx: Context = Depends(get_ctx)):
    if ctx.role != "EMPLOYEE" and not ctx.can("tax.view"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.view")
    emp = await _employee_for(ctx, employee_id)
    if ctx.role == "EMPLOYEE" and emp.get("user_id") != ctx.user_id:
        raise HTTPException(status_code=403, detail="Not your profile")
    fy = _resolve_fy(financial_year)
    return await db.tax_year_profiles.find_one(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "financial_year": fy},
        {"_id": 0, "org_id": 0})


@router.put("/profiles")
async def put_tax_profile(input: TaxYearProfileIn, employee_id: str | None = None,
                          ctx: Context = Depends(get_ctx)):
    if not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    emp = await _employee_for(ctx, employee_id)
    doc = await upsert_tax_profile(ctx.org_id, emp["id"], input, ctx.user)
    doc.pop("org_id", None)
    return doc
