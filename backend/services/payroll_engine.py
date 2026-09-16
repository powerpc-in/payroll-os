"""The deterministic payroll engine.

Jurisdiction-agnostic by contract: the engine receives a `StatutoryContext`
(rules resolved by services.rules for a jurisdiction + state + effective date)
and a salary structure, and produces fully explained line items. It contains no
country-specific constants — every rate, threshold and slab comes from a
versioned rule document, and each result snapshots the rule versions used
(payroll results are immutable history: adding FY rules later never rewrites an
old run).

Fail-safe: a missing or unverified statutory rule raises RuleUnavailable, which
marks that employee's row as an error with the reason — a guessed deduction is
never produced.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

from services.rules import RuleUnavailable, rule_ref

def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def period_bounds(period: str) -> tuple[str, str, int]:
    """'2026-01' → ('2026-01-01', '2026-01-31', 31 days)."""
    year, month = int(period[:4]), int(period[5:7])
    days = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{days:02d}", days


def fy_of_period(period: str) -> tuple[int, int, str]:
    """'2026-01' → (2025, 10, 'FY 2025-26') for the India April–March tax year.

    The month arithmetic (April start) is a jurisdiction calendar property and is
    supplied by the org's jurisdiction config — this helper stays generic for
    April-start tax years, which India uses.
    """
    year, month = int(period[:4]), int(period[5:7])
    fy_start = year if month >= 4 else year - 1
    months_elapsed = (month - 4) % 12 + 1
    return fy_start, months_elapsed, f"FY {fy_start}-{(fy_start + 1) % 100:02d}"


def compute_paid_days(total_days: int, attendance_summary: dict[str, float]) -> tuple[float, float]:
    """LOP-based: paid factor = (total - lop) / total. Unpaid leave and absences are LOP."""
    lop = (
        attendance_summary.get("absent", 0)
        + attendance_summary.get("unpaid_leave", 0)
        + 0.5 * attendance_summary.get("half_day", 0)
    )
    lop = min(lop, float(total_days))
    paid = float(total_days) - lop
    return paid, lop


def compute_employee_payroll(
    *,
    employee: dict,
    period: str,
    assignment: dict,
    structure: dict,
    attendance_summary: dict[str, float],
    inputs: list[dict],
    loan_items: list[dict],
    declarations: dict,
    ytd_tds: float,
    rules: dict[str, dict | None],
    months_elapsed_in_fy: int,
    accept_unverified: bool,
) -> dict:
    """Pure computation for one employee for one period. Returns the result document
    (without run/org identity) or raises RuleUnavailable."""
    _, _, total_days = period_bounds(period)
    paid_days, lop_days = compute_paid_days(total_days, attendance_summary)
    factor = paid_days / total_days
    gross_target = float(assignment["gross_monthly"])

    rule_refs: list[dict] = []
    explain_prefix = f"{period} · {total_days} calendar days · {lop_days:g} LOP day(s)"

    # ---- recurring earnings (structure components) -------------------------
    comps = monthly_components(structure, gross_target)
    earnings: list[dict] = []
    gross_monthly = 0.0
    basic_monthly = next((c["monthly"] for c in comps if c["code"] == "BASIC"), 0.0)
    hra_monthly = next((c["monthly"] for c in comps if c["code"] == "HRA"), 0.0)
    for comp in comps:
        calc = comp["calc"]
        monthly = comp["monthly"]
        if calc == "pct_gross":
            formula = f"{comp['value']:g}% of gross ₹{gross_target:,.0f}"
        elif calc == "pct_basic":
            formula = f"{comp['value']:g}% of basic ₹{basic_monthly:,.0f}"
        elif calc == "fixed":
            formula = f"Fixed ₹{monthly:,.0f}/month"
        elif calc == "gross_balance":
            formula = f"Balance of gross: ₹{gross_target:,.0f} − other components"
        else:
            formula = f"Unsupported calc '{calc}' — treated as 0"
        earned = _r2(monthly * factor)
        gross_monthly = _r2(gross_monthly + monthly)
        earnings.append({
            "code": comp["code"], "name": comp["name"], "category": "earning",
            "monthly": monthly, "amount": earned, "taxable": comp.get("taxable", True),
            "pf_applicable": comp.get("pf_applicable", comp["code"] == "BASIC"),
            "esi_applicable": comp.get("esi_applicable", True),
            "explanation": {
                "input": f"{comp['name']}: {formula} · paid factor {factor:.4f} ({explain_prefix})",
                "rule": "Salary structure component",
                "calculation": f"₹{monthly:,.2f} × {factor:.4f} = ₹{earned:,.2f}",
            },
        })

    # ---- one-time inputs ----------------------------------------------------
    for inp in inputs:
        earned = _r2(float(inp["amount"]))
        gross_monthly = _r2(gross_monthly + earned)
        earnings.append({
            "code": inp["input_type"].upper(), "name": inp["note"] or inp["input_type"].title(),
            "category": "earning", "monthly": earned, "amount": earned,
            "taxable": inp.get("taxable", True),
            "explanation": {
                "input": f"Payroll input · {inp['input_type']}" + (f" · {inp['note']}" if inp.get("note") else ""),
                "rule": "Manual payroll input (reviewed in the run)",
                "calculation": f"Entered amount ₹{earned:,.2f}",
            },
        })

    gross_earnings = _r2(sum(e["amount"] for e in earnings))
    taxable_gross = _r2(sum(e["amount"] for e in earnings if e["taxable"]))

    # ---- statutory: PF -------------------------------------------------------
    deductions: list[dict] = []
    employer_contributions: list[dict] = []
    pf_rule = rules.get("pf")
    pf_wage = _r2(sum(
        e["amount"] for e in earnings
        if e["code"] in ("BASIC",) or (e.get("pf_applicable") and e["category"] == "earning")
    ))
    if employee.get("pf_applicable") and pf_rule is not None:
        rule_refs.append(rule_ref(pf_rule))
        p = pf_rule["params"]
        ee_rate, er_rate = float(p["employee_rate"]), float(p["employer_rate"])
        ee_pf = _r2(pf_wage * ee_rate)
        er_pf = _r2(pf_wage * er_rate)
        ceiling = p.get("wage_ceiling")
        eps_wage = min(pf_wage, float(ceiling)) if ceiling else pf_wage
        eps = _r2(eps_wage * float(p["eps_rate"]))
        deductions.append({
            "code": "PF", "name": "Provident Fund (employee)", "category": "deduction",
            "amount": ee_pf,
            "explanation": {
                "input": f"PF wages ₹{pf_wage:,.2f} (earned basic + PF-applicable pay)",
                "rule": f"{pf_rule.get('source', 'PF rules')} v{pf_rule.get('version')}"
                        + ("" if pf_rule.get("verified") else " · requires statutory verification"),
                "formula": f"Employee {pct(ee_rate)} of PF wages" + (f", EPS wage ceiling ₹{ceiling:,.0f}" if ceiling else ""),
                "calculation": f"{pct(ee_rate)} × ₹{pf_wage:,.2f} = ₹{ee_pf:,.2f}",
            },
        })
        employer_contributions.append({
            "code": "EPF_ER", "name": "EPF (employer)", "category": "employer_contribution",
            "amount": _r2(er_pf - eps),
            "explanation": {
                "input": f"PF wages ₹{pf_wage:,.2f}",
                "rule": f"{pf_rule.get('source', 'PF rules')} v{pf_rule.get('version')}"
                        + ("" if pf_rule.get("verified") else " · requires statutory verification"),
                "formula": f"Employer {pct(er_rate)} split: EPF share (EPS {pct(float(p['eps_rate']))} of "
                           f"{'ceiling ₹' + format(eps_wage, ',.0f') if ceiling else 'full PF wages'})",
                "calculation": f"{pct(er_rate)} × ₹{pf_wage:,.2f} = ₹{er_pf:,.2f}; EPS {pct(float(p['eps_rate']))} × ₹{eps_wage:,.2f} = ₹{eps:,.2f}",
            },
        })
        employer_contributions.append({
            "code": "EPS_ER", "name": "EPS (employer, pension)", "category": "employer_contribution",
            "amount": eps,
            "explanation": {
                "input": f"EPS wage ₹{eps_wage:,.2f}" + (f" (ceiling ₹{ceiling:,.0f})" if ceiling else ""),
                "rule": f"{pf_rule.get('source', 'PF rules')} v{pf_rule.get('version')}",
                "formula": f"EPS {pct(float(p['eps_rate']))} of EPS wage (part of employer 12%)",
                "calculation": f"{pct(float(p['eps_rate']))} × ₹{eps_wage:,.2f} = ₹{eps:,.2f}",
            },
        })

    # ---- statutory: ESI -------------------------------------------------------
    esi_rule = rules.get("esi")
    esi_gross_limit = float(esi_rule["params"]["gross_limit"]) if esi_rule else 0
    if employee.get("esi_applicable") and esi_rule is not None and gross_earnings <= esi_gross_limit:
        rule_refs.append(rule_ref(esi_rule))
        p = esi_rule["params"]
        ee_esi = _r2(gross_earnings * float(p["employee_rate"]))
        er_esi = _r2(gross_earnings * float(p["employer_rate"]))
        deductions.append({
            "code": "ESI", "name": "ESI (employee)", "category": "deduction", "amount": ee_esi,
            "explanation": {
                "input": f"Gross ₹{gross_earnings:,.2f} ≤ threshold ₹{esi_gross_limit:,.0f}",
                "rule": f"{esi_rule.get('source', 'ESI rules')} v{esi_rule.get('version')}"
                        + ("" if esi_rule.get("verified") else " · requires statutory verification"),
                "formula": f"Employee {pct(float(p['employee_rate']))} of gross",
                "calculation": f"{pct(float(p['employee_rate']))} × ₹{gross_earnings:,.2f} = ₹{ee_esi:,.2f}",
            },
        })
        employer_contributions.append({
            "code": "ESI_ER", "name": "ESI (employer)", "category": "employer_contribution",
            "amount": er_esi,
            "explanation": {
                "input": f"Gross ₹{gross_earnings:,.2f}",
                "rule": f"{esi_rule.get('source', 'ESI rules')} v{esi_rule.get('version')}",
                "formula": f"Employer {pct(float(p['employer_rate']))} of gross",
                "calculation": f"{pct(float(p['employer_rate']))} × ₹{gross_earnings:,.2f} = ₹{er_esi:,.2f}",
            },
        })

    # ---- statutory: PT & LWF (state-aware) ------------------------------------
    state = employee.get("state") or employee.get("work_state")
    pt_rule = rules.get("pt")
    if pt_rule is not None:
        rule_refs.append(rule_ref(pt_rule))
        slab = pt_applicable_amount(pt_rule["params"], gross_earnings)
        if slab > 0:
            deductions.append({
                "code": "PT", "name": f"Professional Tax ({state or 'state'})", "category": "deduction",
                "amount": _r2(slab),
                "explanation": {
                    "input": f"Gross ₹{gross_earnings:,.2f} · state {state}",
                    "rule": f"{pt_rule.get('source', 'PT rules')} v{pt_rule.get('version')}"
                            + ("" if pt_rule.get("verified") else " · requires statutory verification"),
                    "formula": "State PT slab for gross band",
                    "calculation": f"Slab amount ₹{slab:,.2f}",
                },
            })
    lwf_rule = rules.get("lwf")
    if lwf_rule is not None:
        rule_refs.append(rule_ref(lwf_rule))
        p = lwf_rule["params"]
        ee_lwf = _r2(float(p["employee"]))
        er_lwf = _r2(float(p["employer"]))
        deductions.append({
            "code": "LWF", "name": f"Labour Welfare Fund ({state or 'state'})", "category": "deduction",
            "amount": ee_lwf,
            "explanation": {
                "input": f"State {state} · monthly contribution",
                "rule": f"{lwf_rule.get('source', 'LWF rules')} v{lwf_rule.get('version')}"
                        + ("" if lwf_rule.get("verified") else " · requires statutory verification"),
                "formula": f"Employee ₹{ee_lwf:,.0f} / month",
                "calculation": f"Flat ₹{ee_lwf:,.2f}",
            },
        })
        employer_contributions.append({
            "code": "LWF_ER", "name": f"LWF employer share ({state or 'state'})", "category": "employer_contribution",
            "amount": er_lwf,
            "explanation": {
                "input": f"State {state} · monthly contribution",
                "rule": f"{lwf_rule.get('source', 'LWF rules')} v{lwf_rule.get('version')}",
                "formula": f"Employer ₹{er_lwf:,.0f} / month",
                "calculation": f"Flat ₹{er_lwf:,.2f}",
            },
        })

    # ---- statutory: TDS (regime chosen by employee, rules versioned) ----------
    from services import tax_engine
    it_rule = rules.get("income_tax")
    if it_rule is not None:
        rule_refs.append(rule_ref(it_rule))
        regime = employee.get("tax_regime") or "new"
        regime_key = "income_tax_new_regime" if regime == "new" else "income_tax_old_regime"
        projection = tax_engine.project_annual_taxable(
            taxable_gross, months_elapsed_in_fy, regime, it_rule["params"],
            declarations, basic_monthly, hra_monthly,
        )
        tax = tax_engine.compute_income_tax(projection["taxable"], it_rule["params"])
        monthly_tds = tax_engine.tds_for_month(tax["total_annual_tax"], months_elapsed_in_fy, ytd_tds)
        if monthly_tds > 0:
            deductions.append({
                "code": "TDS", "name": f"TDS on salary ({regime.title()} regime)", "category": "deduction",
                "amount": monthly_tds,
                "explanation": {
                    "input": f"Projected taxable {projection['gross_annual'] + projection['other_income']:,.0f} gross "
                             f"→ ₹{projection['taxable']:,.0f} taxable · {months_elapsed_in_fy} months elapsed in FY · YTD TDS ₹{ytd_tds:,.0f}",
                    "rule": f"Income-tax {regime.title()} regime, {it_rule.get('source', 'Finance Act')} v{it_rule.get('version')}"
                            + ("" if it_rule.get("verified") else " · requires statutory verification"),
                    "formula": f"Slab tax + cess − rebate 87A, ÷ 12 × {months_elapsed_in_fy} − YTD",
                    "calculation": f"Annual tax ₹{tax['total_annual_tax']:,.2f} → due-to-date ₹"
                                   f"{round(tax['total_annual_tax'] / 12 * months_elapsed_in_fy, 2):,.2f} − YTD ₹{ytd_tds:,.2f}",
                },
            })

    # ---- loan EMIs -------------------------------------------------------------
    for li in loan_items:
        deductions.append({
            "code": "LOAN", "name": f"Loan EMI · {li['loan_name']}", "category": "deduction",
            "amount": _r2(li["emi"]),
            "explanation": {
                "input": f"Loan {li['loan_name']} · outstanding ₹{li['outstanding']:,.2f}",
                "rule": "Approved loan repayment schedule",
                "formula": f"EMI ₹{li['emi']:,.2f} (principal ₹{li['principal_part']:,.2f} + interest ₹{li['interest_part']:,.2f})",
                "calculation": f"Scheduled instalment from loan #{li['loan_id'][:8]}",
            },
        })

    total_deductions = _r2(sum(d["amount"] for d in deductions))
    total_employer = _r2(sum(c["amount"] for c in employer_contributions))
    net_pay = _r2(gross_earnings - total_deductions)

    return {
        "period": period,
        "employee_id": employee["id"],
        "employee_snapshot": {
            "name": employee["name"], "employee_code": employee.get("employee_code"),
            "department": employee.get("department_name"), "designation": employee.get("designation"),
            "location": employee.get("location_name"), "state": state,
            "cost_centre": employee.get("cost_centre"),
            "pan_masked": mask_pan(employee.get("pan")), "tax_regime": employee.get("tax_regime") or "new",
        },
        "paid_days": paid_days, "lop_days": lop_days, "total_days": total_days,
        "earnings": earnings, "deductions": deductions, "employer_contributions": employer_contributions,
        "gross_earnings": gross_earnings, "taxable_gross": taxable_gross,
        "total_deductions": total_deductions, "total_employer_contributions": total_employer,
        "net_pay": net_pay, "employer_cost": _r2(gross_earnings + total_employer),
        "tax_projection": None, "status": "ok", "error_reason": None,
        "rule_refs": rule_refs,
        "computed_with_unverified_rules": any(not r["verified"] for r in rule_refs),
    }


def pt_applicable_amount(params: dict, gross: float) -> float:
    """params: {"slabs": [{"min": 0, "amount": 0}, ...]} — highest matching band wins."""
    amount = 0.0
    for slab in params.get("slabs", []):
        if gross >= float(slab["min"]):
            amount = max(amount, float(slab["amount"]))
    return amount


def monthly_components(structure: dict, gross_target: float) -> list[dict]:
    """Full-month component amounts for a gross target — shared by the payroll
    engine and the tax projection so both never diverge."""
    comps = sorted(structure.get("components", []), key=lambda c: 0 if c["calc"] != "gross_balance" else 1)
    monthly_by_code: dict[str, float] = {}
    basic_monthly = 0.0
    out: list[dict] = []
    for comp in comps:
        calc = comp["calc"]
        if calc == "pct_gross":
            monthly = _r2(gross_target * float(comp["value"]) / 100.0)
        elif calc == "pct_basic":
            monthly = _r2(basic_monthly * float(comp["value"]) / 100.0) if basic_monthly > 0 else 0.0
        elif calc == "fixed":
            monthly = _r2(float(comp["value"]))
        elif calc == "gross_balance":
            monthly = _r2(gross_target - sum(monthly_by_code.values()))
        else:
            monthly = 0.0
        if comp["code"] == "BASIC":
            basic_monthly = monthly
        monthly_by_code[comp["code"]] = monthly
        out.append({
            "code": comp["code"], "name": comp["name"], "calc": calc, "value": comp.get("value", 0),
            "monthly": monthly, "taxable": comp.get("taxable", True),
            "pf_applicable": comp.get("pf_applicable", comp["code"] == "BASIC"),
            "esi_applicable": comp.get("esi_applicable", True),
        })
    return out


def pct(rate: float) -> str:
    return f"{round(rate * 100, 2):g}%"


def mask_pan(pan: str | None) -> str | None:
    if not pan:
        return pan
    return "X" * max(0, len(pan) - 4) + pan[-4:]


def mask_account(acc: str | None) -> str | None:
    if not acc:
        return acc
    return "X" * max(0, len(acc) - 4) + acc[-4:]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
