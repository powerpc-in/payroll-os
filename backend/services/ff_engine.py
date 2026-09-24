"""Full & Final settlement engine — deterministic, explainable, jurisdiction-aware.

Every line carries an explanation block (INPUT → RULE → FORMULA → CALCULATION → RESULT)
and, where a statutory rule is involved, the exact rule version used at computation time.
Nothing is guessed: if a statutory rule is missing or unverified (and the org has not opted
into unverified values) the line is NOT computed — a note records why.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone

from lib.db import db
from services import payroll_engine
from services.rules import RuleUnavailable, get_rule, rule_ref

VERIFY_NOTE = "Requires statutory verification"


def _r2(x: float) -> float:
    return round(float(x or 0), 2)


def _explain(input_: str, rule: str, formula: str, calculation: str) -> dict:
    return {"input": input_, "rule": rule, "formula": formula, "calculation": calculation}


def _line(code: str, name: str, amount: float, explanation: dict,
          rule: dict | None = None) -> dict:
    line = {"code": code, "name": name, "amount": _r2(amount), "explanation": explanation}
    if rule is not None:
        line["rule_ref"] = rule_ref(rule)
    return line


async def compute_settlement(org: dict, emp: dict, input_: dict) -> dict:
    """Pure-ish computation: reads the employee's live records, returns the settlement doc
    body (without id/status/audit fields). Never writes."""
    org_id = org["id"]
    lwd_str: str = input_["last_working_day"]
    lwd = date.fromisoformat(lwd_str)
    period = lwd_str[:7]
    total_days = monthrange(lwd.year, lwd.month)[1]

    assignment = await db.salary_assignments.find_one(
        {"org_id": org_id, "employee_id": emp["id"], "active": True})
    if not assignment:
        raise ValueError("No active salary assignment — assign a salary structure first")
    structure = await db.salary_structures.find_one(
        {"id": assignment["structure_id"], "org_id": org_id})
    gross_monthly = float(assignment["gross_monthly"])
    comps = payroll_engine.monthly_components(structure, gross_monthly)
    basic_monthly = float(next((c["monthly"] for c in comps if c["code"] == "BASIC"), 0.0))

    payable: list[dict] = []
    recoveries: list[dict] = []
    notes: list[str] = []

    # ---------- 1. Salary payable for days served in the exit month ----------
    locked_run = await db.payroll_runs.find_one(
        {"org_id": org_id, "period": period, "status": "locked"})
    covered = False
    if locked_run:
        row = await db.payroll_employees.find_one(
            {"org_id": org_id, "run_id": locked_run["id"], "employee_id": emp["id"]})
        covered = bool(row and row.get("status") == "ok")
    if covered:
        notes.append(f"Salary for {period} was already paid through the locked payroll run "
                     f"{locked_run['id'][:8]} — it is not repeated here.")
        worked_days = 0.0
    else:
        worked_days = float(min(lwd.day, total_days))
        amount = gross_monthly / total_days * worked_days
        payable.append(_line(
            "SALARY_PAYABLE", f"Salary payable ({period}, {worked_days:g}/{total_days} days)",
            amount,
            _explain(f"Served {worked_days:g} of {total_days} day(s) up to {lwd_str}",
                     "Pro-rata salary on the active salary structure",
                     "gross_monthly / days_in_month x days_served",
                     f"{gross_monthly:,.2f} / {total_days} x {worked_days:g} = {_r2(amount):,.2f}")))

    # ---------- 2. Unpaid leave / absence (loss of pay) in the exit month ----------
    if worked_days:
        att = await db.attendance.find({
            "org_id": org_id, "employee_id": emp["id"],
            "date": {"$gte": f"{period}-01", "$lte": lwd_str}}).to_list(200)
        summary: dict[str, float] = {}
        for a in att:
            summary[a.get("status", "present")] = summary.get(a.get("status", "present"), 0.0) + float(a.get("days", 1))
        lop_days = summary.get("absent", 0.0) + summary.get("unpaid_leave", 0.0) \
            + 0.5 * summary.get("half_day", 0.0)
        if lop_days > 0:
            amount = gross_monthly / total_days * lop_days
            recoveries.append(_line(
                "LOP", "Loss of pay (unpaid leave / absence)", amount,
                _explain(f"{lop_days:g} LOP day(s) between {period}-01 and {lwd_str}",
                         "Attendance-driven LOP (absent + unpaid leave + 0.5 x half day)",
                         "gross_monthly / days_in_month x lop_days",
                         f"{gross_monthly:,.2f} / {total_days} x {lop_days:g} = {_r2(amount):,.2f}")))

    # ---------- 3. Notice period pay / recovery ----------
    notice_pay_days = float(input_.get("notice_pay_days") or 0)
    if notice_pay_days > 0:
        amount = gross_monthly / 30 * notice_pay_days
        payable.append(_line(
            "NOTICE_PAY", "Notice period pay (in lieu of notice)", amount,
            _explain(f"{notice_pay_days:g} day(s) paid in lieu",
                     "Company notice policy (contractual, not statutory)",
                     "gross_monthly / 30 x days",
                     f"{gross_monthly:,.2f} / 30 x {notice_pay_days:g} = {_r2(amount):,.2f}")))
    notice_rec_days = float(input_.get("notice_recovery_days") or 0)
    if notice_rec_days > 0:
        amount = gross_monthly / 30 * notice_rec_days
        recoveries.append(_line(
            "NOTICE_REC", "Notice period shortfall recovery", amount,
            _explain(f"{notice_rec_days:g} day(s) of notice not served",
                     "Company notice policy (contractual, not statutory)",
                     "gross_monthly / 30 x days",
                     f"{gross_monthly:,.2f} / 30 x {notice_rec_days:g} = {_r2(amount):,.2f}")))

    # ---------- 4. Leave encashment on earned-leave balance ----------
    balances = await db.leave_balances.find(
        {"org_id": org_id, "employee_id": emp["id"]}).to_list(50)
    lts = {t["id"]: t for t in await db.leave_types.find({"org_id": org_id}).to_list(50)}
    detail: list[str] = []
    encash_days = 0.0
    for b in balances:
        lt = lts.get(b.get("leave_type_id")) or {}
        if not lt.get("encashable", lt.get("paid", True)):
            continue
        avail = max(0.0, float(b.get("granted", 0)) - float(b.get("used", 0)))
        if avail > 0:
            encash_days += avail
            detail.append(f"{lt.get('code') or lt.get('name', 'leave')} {avail:g}d")
    override = input_.get("encash_days_override")
    if override is not None:
        encash_days = float(override)
        detail = [f"override {encash_days:g}d"]
    if encash_days > 0:
        per_day = basic_monthly / 30
        amount = per_day * encash_days
        payable.append(_line(
            "LEAVE_ENCASH", "Leave encashment", amount,
            _explain(f"{encash_days:g} encashable day(s) ({', '.join(detail)})",
                     "Company leave-encashment policy on earned/paid leave balances",
                     "basic_monthly / 30 x encashable_days",
                     f"{basic_monthly:,.2f} / 30 x {encash_days:g} = {_r2(amount):,.2f}")))

    # ---------- 5. Bonus / incentive / other payables ----------
    for key, code, label in (("bonus", "BONUS", "Bonus"),
                             ("incentive", "INCENTIVE", "Incentive / commission"),
                             ("other_earnings", "OTHER_PAY", "Other payable")):
        val = float(input_.get(key) or 0)
        if val:
            payable.append(_line(
                code, label, val,
                _explain("Entered by the payroll administrator at settlement",
                         "Company policy (not statutory)", "Flat amount",
                         f"{_r2(val):,.2f}")))

    # ---------- 6. Approved but unpaid reimbursements ----------
    reimb = await db.reimbursements.find({
        "org_id": org_id, "employee_id": emp["id"], "status": "approved",
        "paid_run_id": None}).to_list(200)
    reimb_total = _r2(sum(float(r.get("approved_amount") or 0) for r in reimb))
    if reimb_total > 0:
        payable.append(_line(
            "REIMB", "Approved reimbursements (unpaid)", reimb_total,
            _explain(f"{len(reimb)} approved claim(s) not yet paid through payroll",
                     "Reimbursement policy", "Sum of approved amounts",
                     f"{reimb_total:,.2f}")))

    # ---------- 7. Gratuity (statutory rule, fail-safe) ----------
    gratuity_note = None
    allow_unverified = bool((org.get("payroll_settings") or {}).get(
        "accept_unverified_statutory_values", False))
    try:
        g_rule = await get_rule(org_id, org.get("jurisdiction", "IN"), "gratuity",
                                lwd_str, None, allow_unverified)
        params = g_rule.get("params") or {}
        doj = emp.get("joining_date") or lwd_str
        try:
            years = round((lwd - date.fromisoformat(doj)).days / 365.25, 2)
        except ValueError:
            years = 0.0
        eligibility = float(params.get("eligibility_years", 5))
        if years >= eligibility:
            numerator = float(params.get("days_per_year", 15))
            denominator = float(params.get("month_days", 26))
            amount = basic_monthly / denominator * numerator * years
            cap = params.get("max_amount")
            capped = False
            if cap and amount > float(cap):
                amount, capped = float(cap), True
            payable.append(_line(
                "GRATUITY", "Gratuity", amount,
                _explain(f"{years:g} year(s) of service (joined {doj}, LWD {lwd_str})",
                         f"{g_rule.get('source') or 'Gratuity rules'} v{g_rule.get('version')}"
                         + ("" if g_rule.get("verified") else f" · {VERIFY_NOTE}"),
                         f"{numerator:g}/{denominator:g} x last drawn basic x years"
                         + (" (statutory ceiling applied)" if capped else ""),
                         f"{numerator:g}/{denominator:g} x {basic_monthly:,.2f} x {years:g}"
                         f" = {_r2(amount):,.2f}"),
                rule=g_rule))
        else:
            gratuity_note = (f"Gratuity not payable: {years:g} year(s) of service is below the "
                             f"{eligibility:g}-year eligibility threshold in the applicable rule.")
    except RuleUnavailable as exc:
        gratuity_note = f"Gratuity not computed — {exc}. {VERIFY_NOTE}."

    # ---------- 8. Loan / advance recovery ----------
    loans = await db.loans.find({"org_id": org_id, "employee_id": emp["id"],
                                 "status": "active"}).to_list(50)
    loan_outstanding = _r2(sum(float(l.get("outstanding") or 0) for l in loans))
    if loan_outstanding > 0:
        recoveries.append(_line(
            "LOAN_REC", "Loan / advance recovery (full outstanding)", loan_outstanding,
            _explain(f"{len(loans)} active loan/advance: "
                     + ", ".join(f"{l.get('name', 'loan')} {_r2(l.get('outstanding')):,.2f}" for l in loans),
                     "Loan agreement — balance recovered on exit",
                     "Sum of outstanding principal", f"{loan_outstanding:,.2f}")))

    other_ded = float(input_.get("other_deductions") or 0)
    if other_ded:
        recoveries.append(_line(
            "OTHER_DED", "Other deductions", other_ded,
            _explain("Entered by the payroll administrator at settlement",
                     "Company policy (not statutory)", "Flat amount", f"{_r2(other_ded):,.2f}")))

    total_payable = _r2(sum(p["amount"] for p in payable))
    total_recoveries = _r2(sum(r["amount"] for r in recoveries))
    tax_adjustment = _r2(input_.get("tax_adjustment") or 0)
    net = _r2(total_payable - total_recoveries - tax_adjustment)

    unverified = any(p.get("rule_ref", {}).get("verified") is False for p in payable)

    return {
        "employee_id": emp["id"], "employee_name": emp["name"],
        "employee_code": emp.get("employee_code"),
        "department": emp.get("department_name"), "location": emp.get("location_name"),
        "joining_date": emp.get("joining_date"),
        "last_working_day": lwd_str, "period": period,
        "exit_reason": input_.get("exit_reason"),
        "notes": input_.get("notes"),
        "payable": payable, "recoveries": recoveries,
        "tax_adjustment": tax_adjustment,
        "tax_adjustment_note": (
            "Final TDS/tax adjustment on settlement is entered by the payroll administrator — "
            f"the engine does not guess it. {VERIFY_NOTE} before payout."),
        "total_payable": total_payable, "total_recoveries": total_recoveries,
        "net_settlement": net,
        "gratuity_note": gratuity_note,
        "computation_notes": notes,
        "computed_with_unverified_rules": unverified,
        "reimbursement_ids": [r["id"] for r in reimb],
        "loan_ids": [l["id"] for l in loans],
        "currency": org.get("currency", "INR"),
        "jurisdiction": org.get("jurisdiction", "IN"),
        "computed_at": datetime.now(timezone.utc),
    }
