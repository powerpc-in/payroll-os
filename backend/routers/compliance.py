"""Compliance: versioned statutory rules (with verification flags) and
Full & Final settlement computation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from services import payroll_engine
from services.rules import RuleUnavailable, get_rule, rule_ref

router = APIRouter(prefix="/v1/compliance", tags=["Compliance"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class RuleIn(BaseModel):
    jurisdiction: str
    rule_type: str
    state: str | None = None
    params: dict
    effective_from: str
    effective_to: str | None = None
    source: str | None = None
    source_date: str | None = None
    verified: bool = False
    notes: str | None = None


@router.get("/rules")
async def list_rules(ctx: Context = Depends(require_perm("compliance.view")),
                     jurisdiction: str | None = None, rule_type: str | None = None,
                     state: str | None = None, active: bool | None = None):
    query: dict = {}
    if jurisdiction:
        query["jurisdiction"] = jurisdiction
    if rule_type:
        query["rule_type"] = rule_type
    if state:
        query["state"] = state
    if active is not None:
        query["active"] = active
    docs = await db.statutory_rules.find(query).sort([
        ("jurisdiction", 1), ("rule_type", 1), ("state", 1), ("version", -1)]).to_list(500)
    for d in docs:
        d.pop("_id", None)
        d["verification_status"] = "verified" if d.get("verified") else "Requires statutory verification"
    return docs


@router.post("/rules")
async def add_rule_version(input: RuleIn, ctx: Context = Depends(require_perm("compliance.manage"))):
    """Manually enter a NEW rule version — typically after independently verifying
    the values offline. The system never marks a rule verified on its own."""
    last = await db.statutory_rules.find_one(
        {"jurisdiction": input.jurisdiction, "rule_type": input.rule_type, "state": input.state},
        sort=[("version", -1)])
    doc = input.model_dump()
    doc["id"] = new_id()
    doc["version"] = (last or {}).get("version", 0) + 1
    doc["org_id"] = ctx.org_id
    doc["created_by"] = ctx.user["email"]
    doc["created_at"] = now()
    await db.statutory_rules.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "compliance.rule_added", actor=ctx.user, entity="statutory_rule",
               entity_id=doc["id"],
               summary=f"Statutory rule {input.rule_type} v{doc['version']} added "
                       f"({'verified' if input.verified else 'REQUIRES STATUTORY VERIFICATION'})")
    return doc


class FFIn(BaseModel):
    employee_id: str
    last_working_day: str
    notice_pay_days: float = 0  # notice period served short → recovery; extra served → payable
    notice_recovery_days: float = 0
    other_earnings: float = 0
    other_deductions: float = 0
    tax_adjustment: float = 0
    notes: str | None = None


@router.get("/ff")
async def list_ff(ctx: Context = Depends(require_perm("payroll.view")), employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    docs = await db.ffs.find(query).sort("created_at", -1).to_list(100)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/ff")
async def create_ff(input: FFIn, ctx: Context = Depends(require_perm("payroll.calculate"))):
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    assignment = await db.salary_assignments.find_one(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "active": True})
    if not assignment:
        raise HTTPException(status_code=400, detail="No active salary assignment")
    structure = await db.salary_structures.find_one({"id": assignment["structure_id"]})
    comps = payroll_engine.monthly_components(structure, assignment["gross_monthly"])
    basic_monthly = next((c["monthly"] for c in comps if c["code"] == "BASIC"), 0)
    gross_monthly = assignment["gross_monthly"]

    payable: list[dict] = []
    recoveries: list[dict] = []

    # Unpaid salary for days worked since the last payroll cutoff — approximated by
    # notice pay input for the MVP; final-run payroll covers the regular month.
    if input.notice_pay_days > 0:
        amount = round(gross_monthly / 30 * input.notice_pay_days, 2)
        payable.append({
            "code": "NOTICE_PAY", "name": "Notice period pay",
            "amount": amount,
            "explanation": {"input": f"{input.notice_pay_days:g} day(s)",
                            "rule": "Company notice policy",
                            "formula": "gross_monthly / 30 × days",
                            "calculation": f"₹{gross_monthly:,.2f} / 30 × {input.notice_pay_days:g} = ₹{amount:,.2f}"},
        })

    # Leave encashment on earned leave balance (paid leave types only)
    balances = await db.leave_balances.find({
        "org_id": ctx.org_id, "employee_id": emp["id"]}).to_list(50)
    lts = {t["id"]: t for t in await db.leave_types.find({"org_id": ctx.org_id}).to_list(50)}
    encash_days = 0.0
    for b in balances:
        lt = lts.get(b.get("leave_type_id"))
        if lt and lt.get("paid", True):
            encash_days += max(0.0, float(b.get("granted", 0)) - float(b.get("used", 0)))
    if encash_days > 0:
        per_day = round(basic_monthly / 30, 2)
        amount = round(per_day * encash_days, 2)
        payable.append({
            "code": "LEAVE_ENCASH", "name": "Leave encashment",
            "amount": amount,
            "explanation": {"input": f"{encash_days:g} earned leave day(s) balance",
                            "rule": "Leave encashment policy (earned leave)",
                            "formula": "basic / 30 × balance days",
                            "calculation": f"₹{basic_monthly:,.2f} / 30 × {encash_days:g} = ₹{amount:,.2f}"},
        })

    if input.other_earnings:
        payable.append({"code": "OTHER", "name": "Other payable (bonus/incentive)",
                        "amount": round(input.other_earnings, 2),
                        "explanation": {"input": "Entered at settlement", "rule": "Manual",
                                        "formula": "Flat amount", "calculation": "—"}})

    # Approved-but-unpaid reimbursements
    reimb = await db.reimbursements.find({
        "org_id": ctx.org_id, "employee_id": emp["id"], "status": "approved", "paid_run_id": None,
    }).to_list(100)
    reimb_total = round(sum(r.get("approved_amount", 0) for r in reimb), 2)
    if reimb_total > 0:
        payable.append({"code": "REIMB", "name": "Approved reimbursements", "amount": reimb_total,
                        "explanation": {"input": f"{len(reimb)} approved claim(s)",
                                        "rule": "Reimbursement policy", "formula": "Sum of approved amounts",
                                        "calculation": f"₹{reimb_total:,.2f}"}})

    # Gratuity (jurisdiction rule, fail-safe)
    gratuity_note = None
    try:
        org = await db.organisations.find_one({"id": ctx.org_id})
        allow = org.get("payroll_settings", {}).get("accept_unverified_statutory_values", False)
        g_rule = await get_rule(ctx.org_id, org.get("jurisdiction", "IN"), "gratuity",
                                input.last_working_day, None, allow)
        params = g_rule["params"]
        doj = emp.get("joining_date") or input.last_working_day
        years = 0.0
        try:
            from datetime import date
            years = round((date.fromisoformat(input.last_working_day) -
                           date.fromisoformat(doj)).days / 365.25, 2)
        except ValueError:
            pass
        if years >= float(params.get("eligibility_years", 5)):
            # 15/26 × last drawn basic (DA not tracked separately in the MVP)
            amount = round(basic_monthly / 26 * 15 * years, 2) if basic_monthly else 0
            payable.append({
                "code": "GRATUITY", "name": "Gratuity", "amount": amount,
                "explanation": {"input": f"{years:g} years of service (joined {doj})",
                                "rule": f"{g_rule.get('source', 'Gratuity rules')} v{g_rule.get('version')}"
                                        + ("" if g_rule.get("verified") else " · requires statutory verification"),
                                "formula": "15/26 × last drawn basic × years",
                                "calculation": f"15/26 × ₹{basic_monthly:,.2f} × {years:g} = ₹{amount:,.2f}"},
            })
        else:
            gratuity_note = (f"Not eligible: {years:g} years < eligibility threshold "
                             f"{params.get('eligibility_years', 5):g} years")
    except RuleUnavailable as exc:
        gratuity_note = f"Gratuity not computed: {exc}"

    if input.notice_recovery_days > 0:
        amount = round(gross_monthly / 30 * input.notice_recovery_days, 2)
        recoveries.append({"code": "NOTICE_REC", "name": "Notice period recovery", "amount": amount,
                           "explanation": {"input": f"{input.notice_recovery_days:g} day(s) short",
                                           "rule": "Company notice policy",
                                           "formula": "gross_monthly / 30 × days",
                                           "calculation": f"₹{gross_monthly:,.2f} / 30 × {input.notice_recovery_days:g} = ₹{amount:,.2f}"}})
    loans = await db.loans.find({"org_id": ctx.org_id, "employee_id": emp["id"],
                                 "status": "active"}).to_list(50)
    loan_outstanding = round(sum(l["outstanding"] for l in loans), 2)
    if loan_outstanding > 0:
        recoveries.append({"code": "LOAN_REC", "name": "Loan / advance recovery", "amount": loan_outstanding,
                           "explanation": {"input": f"{len(loans)} active loan(s)",
                                           "rule": "Loan agreements", "formula": "Outstanding principal",
                                           "calculation": f"₹{loan_outstanding:,.2f}"}})
    if input.other_deductions:
        recoveries.append({"code": "OTHER_DED", "name": "Other deductions",
                           "amount": round(input.other_deductions, 2),
                           "explanation": {"input": "Entered at settlement", "rule": "Manual",
                                           "formula": "Flat amount", "calculation": "—"}})

    total_payable = round(sum(p["amount"] for p in payable), 2)
    total_recovery = round(sum(r["amount"] for r in recoveries), 2)
    tax_adj = round(input.tax_adjustment, 2)
    net = round(total_payable - total_recovery - tax_adj, 2)

    doc = {
        "id": new_id(), "org_id": ctx.org_id, "employee_id": emp["id"],
        "employee_name": emp["name"], "employee_code": emp.get("employee_code"),
        "last_working_day": input.last_working_day, "notes": input.notes,
        "payable": payable, "recoveries": recoveries,
        "tax_adjustment": tax_adj,
        "tax_adjustment_note": "Tax adjustment on settlement requires statutory verification — entered manually",
        "total_payable": total_payable, "total_recoveries": total_recovery, "net_settlement": net,
        "gratuity_note": gratuity_note, "status": "draft", "created_by": ctx.user["email"],
        "created_at": now(),
    }
    await db.ffs.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "ff.created", actor=ctx.user, entity="ff", entity_id=doc["id"],
               summary=f"F&F settlement for {emp['name']}: net ₹{net:,.2f}")
    return doc
