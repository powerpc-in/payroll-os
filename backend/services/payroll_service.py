"""Payroll run orchestration: create → calculate (per-employee, fail-safe) →
workflow transitions live in the router. Calculation is a controlled backend
job — the HTTP endpoint schedules it and returns immediately."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from lib.db import db
from lib.events import emit
from lib.auth import new_id
from services import payroll_engine
from services.rules import RuleUnavailable, get_rule, rule_ref
from services.employment_statutory_profiles import apply_context, resolve_context
from services.tax_year_profiles import require_supported_residency, resolve_tax_year_context

logger = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


async def attendance_summary(org_id: str, employee_id: str, period: str) -> dict[str, float]:
    docs = await db.attendance.find({
        "org_id": org_id, "employee_id": employee_id, "period": period,
    }).to_list(100)
    summary = {"present": 0.0, "absent": 0.0, "half_day": 0.0, "paid_leave": 0.0,
               "unpaid_leave": 0.0, "weekly_off": 0.0, "holiday": 0.0, "overtime_hours": 0.0}
    for d in docs:
        status = d.get("status")
        if status in summary and status != "overtime_hours":
            summary[status] += float(d.get("days", 1))
        summary["overtime_hours"] += float(d.get("overtime_hours", 0) or 0)
    return summary


async def loan_emis_for_period(org_id: str, employee_id: str, period: str) -> list[dict]:
    loans = await db.loans.find({"org_id": org_id, "employee_id": employee_id, "status": "active"}).to_list(20)
    items = []
    for loan in loans:
        row = next((r for r in loan.get("schedule", []) if r["period"] == period), None)
        if row:
            items.append({
                "loan_id": loan["id"], "loan_name": loan.get("name", "Loan"),
                "emi": row["emi"], "principal_part": row["principal"], "interest_part": row["interest"],
                "outstanding": loan.get("outstanding", 0),
            })
    return items


async def resolve_employee_rules(org: dict, employee: dict, on_date: str) -> dict[str, dict | None]:
    """Resolve every statutory rule this employee's payroll needs. Raises RuleUnavailable
    on the first missing/unverified rule — a safe failure, never a guess."""
    jur = org.get("jurisdiction", "IN")
    profile, location, establishment = await resolve_context(org["id"], employee, on_date, jur)
    resolved_employee, state = apply_context(employee, profile, location, establishment)
    allow = org.get("payroll_settings", {}).get("accept_unverified_statutory_values", False)
    out: dict[str, dict | None] = {"income_tax": None, "pf": None, "esi": None, "pt": None, "lwf": None}
    out["__employee_overrides"] = {k: v for k, v in resolved_employee.items()
                                   if k in ("state", "work_state", "pf_applicable", "pf_on_higher_wages",
                                            "pt_applicable", "lwf_applicable", "pt_employee_category",
                                            "pf_scheme_category", "lwf_category")}
    regime = employee.get("tax_regime") or "new"
    out["income_tax"] = await get_rule(
        org["id"], jur, f"income_tax_{'new' if regime == 'new' else 'old'}_regime", on_date, None, allow)
    require_supported_residency(out["income_tax"], employee.get("tax_residency_status"), jur)
    if profile and resolved_employee.get("pf_applicable"):
        if not establishment or establishment.get("pf_covered") is None:
            raise RuleUnavailable("employment_profile", jur, state,
                                  "PF establishment coverage is not established for this employment profile")
        if establishment.get("pf_covered") is False:
            resolved_employee["pf_applicable"] = False
            out["__employee_overrides"]["pf_applicable"] = False
        else:
            if profile.get("epf_membership_status") is None:
                raise RuleUnavailable("employment_profile", jur, state,
                                      "EPF membership status is missing from the effective employment profile")
            if profile.get("epf_membership_status") == "not_member":
                resolved_employee["pf_applicable"] = False
                out["__employee_overrides"]["pf_applicable"] = False
            elif profile.get("eps_applicable") is None:
                raise RuleUnavailable("employment_profile", jur, state,
                                      "EPS applicability is missing from the effective employment profile")
            elif profile.get("eps_applicable") is False:
                raise RuleUnavailable("employment_profile", jur, state,
                                      "The current payroll engine cannot safely calculate PF without EPS applicability")
            elif not profile.get("membership_effective_from"):
                raise RuleUnavailable("employment_profile", jur, state,
                                      "PF membership effective date is missing from the employment profile")
            elif profile.get("pf_on_higher_wages") is None:
                raise RuleUnavailable("employment_profile", jur, state,
                                      "Higher-wage PF election status is missing from the employment profile")
    if profile and resolved_employee.get("lwf_applicable"):
        if not establishment or establishment.get("lwf_covered") is None:
            raise RuleUnavailable("employment_profile", jur, state,
                                  "LWF establishment coverage is not established for this employment profile")
        if establishment.get("lwf_covered") is False:
            resolved_employee["lwf_applicable"] = False
            out["__employee_overrides"]["lwf_applicable"] = False

    if resolved_employee.get("pf_applicable"):
        out["pf"] = await get_rule(org["id"], jur, "provident_fund", on_date, None, allow)
    if resolved_employee.get("esi_applicable"):
        out["esi"] = await get_rule(org["id"], jur, "employee_state_insurance", on_date, None, allow)
    if resolved_employee.get("pt_applicable"):
        out["pt"] = await get_rule(org["id"], jur, "professional_tax", on_date, state, allow)
    if resolved_employee.get("lwf_applicable"):
        out["lwf"] = await get_rule(org["id"], jur, "lwf", on_date, state, allow)
    return out


def extract_statutory_totals(result: dict) -> None:
    """Flatten per-statute amounts onto the result row for reports and YTD queries."""
    codes = {d["code"]: d["amount"] for d in result["deductions"]}
    er = {c["code"]: c["amount"] for c in result["employer_contributions"]}
    result["tds_amount"] = codes.get("TDS", 0)
    result["pf_employee"] = codes.get("PF", 0)
    result["pf_employer"] = er.get("EPF_ER", 0) + er.get("EPS_ER", 0)
    result["esi_employee"] = codes.get("ESI", 0)
    result["esi_employer"] = er.get("ESI_ER", 0)
    result["pt_amount"] = codes.get("PT", 0)
    result["lwf_amount"] = codes.get("LWF", 0)


async def prior_payroll_runs(org_id: str, period: str) -> list[dict]:
    """Approved/locked payroll runs earlier in the same Indian financial year."""
    fy_start, _, _ = payroll_engine.fy_of_period(period)
    return await db.payroll_runs.find({
        "org_id": org_id,
        "period": {"$gte": f"{fy_start}-04", "$lt": period},
        "status": {"$in": ["approved", "locked"]},
    }).to_list(200)


async def ytd_tds_for_employee(org_id: str, employee_id: str, prior_run_ids: list[str]) -> float:
    if not prior_run_ids:
        return 0.0
    rows = await db.payroll_employees.find({
        "org_id": org_id, "employee_id": employee_id,
        "run_id": {"$in": prior_run_ids}, "status": {"$ne": "error"},
    }).to_list(100)
    return round(sum(float(row.get("tds_amount", 0) or 0) for row in rows), 2)


def _date_key(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _effective_date_key(value) -> str | None:
    if not value:
        return None
    candidate = value.date().isoformat() if isinstance(value, datetime) else str(value)[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def select_effective_salary_assignment(
    assignments: list[dict], org_id: str, employee_id: str, period: str,
) -> dict | None:
    """Select the latest assignment effective on the first day of a payroll month.

    Payroll currently has no mid-month salary-change proration. Such a change is
    therefore applied from the first payroll month whose first day is on/after
    effective_from.
    """
    period_start = _effective_date_key(f"{period}-01")
    if not period_start:
        return None
    valid = []
    for assignment in assignments:
        if assignment.get("org_id") != org_id or assignment.get("employee_id") != employee_id:
            continue
        effective_from = _effective_date_key(assignment.get("effective_from"))
        if not effective_from or effective_from > period_start:
            continue
        effective_to = _effective_date_key(assignment.get("effective_to"))
        if assignment.get("effective_to") and (not effective_to or effective_to < period_start):
            continue
        valid.append(assignment)
    if not valid:
        return None
    return max(valid, key=lambda a: (
        _effective_date_key(a.get("effective_from")) or "", _date_key(a.get("created_at")),
        str(a.get("id") or ""), str(a.get("structure_id") or ""),
        float(a.get("gross_monthly") or 0),
    ))


def resolve_salary_for_period(
    assignments: list[dict], structures: dict[str, dict],
    org_id: str, employee_id: str, period: str,
) -> tuple[dict, dict]:
    assignment = select_effective_salary_assignment(assignments, org_id, employee_id, period)
    if not assignment:
        raise ValueError(f"No salary assignment effective for payroll period {period}")
    structure = structures.get(assignment.get("structure_id"))
    if not structure or structure.get("org_id") != org_id:
        raise ValueError(f"Assigned salary structure not found in this organisation for period {period}")
    return assignment, structure


async def create_run(org: dict, period: str, actor: dict) -> dict:
    if await db.payroll_runs.find_one({"org_id": org["id"], "period": period}):
        raise ValueError(f"A payroll run for {period} already exists")
    run = {
        "id": new_id(), "org_id": org["id"], "jurisdiction": org.get("jurisdiction", "IN"),
        "period": period, "title": f"Payroll {period}", "status": "draft",
        "totals": {"gross": 0, "net": 0, "deductions": 0, "employer_cost": 0,
                   "headcount": 0, "errors": 0},
        "rule_refs": [],
        "created_at": now(), "created_by": (actor or {}).get("email"),
    }
    await db.payroll_runs.insert_one(run)
    await emit(org["id"], "payroll.created", actor=actor, entity="payroll_run",
               entity_id=run["id"], summary=f"Payroll run created for {period}",
               data={"run_id": run["id"], "period": period})
    return run


async def calculate_run(run_id: str, actor: dict, org_id: str | None = None) -> dict:
    # org_id is passed by the router (already permission-checked) so the service can never
    # be driven to operate on another tenant's run by id alone.
    query = {"id": run_id} if org_id is None else {"id": run_id, "org_id": org_id}
    run = await db.payroll_runs.find_one(query)
    if not run:
        raise ValueError("Payroll run not found")
    if run["status"] not in ("draft", "calculated"):
        raise ValueError(f"Cannot calculate a run in '{run['status']}' state — reverse to draft first")
    org = await db.organisations.find_one({"id": run["org_id"]})
    period = run["period"]
    on_date = f"{period}-01"
    _, months_elapsed, fy_label = payroll_engine.fy_of_period(period)

    employees = await db.employees.find({"org_id": org["id"], "status": "active"}).to_list(2000)
    assignments = await db.salary_assignments.find({"org_id": org["id"]}).to_list(5000)
    assign_by_emp: dict[str, list[dict]] = {}
    for assignment in assignments:
        assign_by_emp.setdefault(assignment["employee_id"], []).append(assignment)
    structures = {s["id"]: s for s in await db.salary_structures.find({"org_id": org["id"]}).to_list(500)}

    prior_runs = await prior_payroll_runs(org["id"], period)
    prior_ids = [r["id"] for r in prior_runs]

    await db.payroll_employees.delete_many({"run_id": run_id})

    totals = {"gross": 0.0, "net": 0.0, "deductions": 0.0, "employer_cost": 0.0,
              "headcount": 0, "errors": 0}
    rule_refs: dict[str, dict] = {}

    async def compute_one(emp: dict) -> None:
        try:
            assignment, structure = resolve_salary_for_period(
                assign_by_emp.get(emp["id"], []), structures, org["id"], emp["id"], period)

            att = await attendance_summary(org["id"], emp["id"], period)
            inputs = await db.payroll_inputs.find({"run_id": run_id, "employee_id": emp["id"]}).to_list(100)
            # Approved-but-unpaid reimbursements feed payroll automatically (spec §15)
            reimb = await db.reimbursements.find({
                "org_id": org["id"], "employee_id": emp["id"],
                "status": "approved", "paid_run_id": None,
            }).to_list(50)
            for r in reimb:
                inputs.append({
                    "input_type": "reimbursement", "amount": r.get("approved_amount", 0),
                    "note": f"{r.get('category', 'Reimbursement')} claim", "taxable": r.get("taxable", False),
                })
            loan_items = await loan_emis_for_period(org["id"], emp["id"], period)
            tax_context = await resolve_tax_year_context(org["id"], emp, period)
            payroll_employee = {**emp, **tax_context["employee_overrides"]}
            decl = tax_context["declarations"]
            ytd_tds = await ytd_tds_for_employee(org["id"], emp["id"], prior_ids)

            rules = await resolve_employee_rules(org, payroll_employee, on_date)
            employee_overrides = rules.pop("__employee_overrides", {})
            result = payroll_engine.compute_employee_payroll(
                employee={**payroll_employee, **employee_overrides}, period=period, assignment=assignment, structure=structure,
                attendance_summary=att, inputs=inputs, loan_items=loan_items,
                declarations=decl, ytd_tds=ytd_tds, rules=rules,
                months_elapsed_in_fy=months_elapsed,
                accept_unverified=org.get("payroll_settings", {}).get("accept_unverified_statutory_values", False),
            )
            extract_statutory_totals(result)
            result.update({
                "id": new_id(),
                "run_id": run_id, "org_id": org["id"], "fy": fy_label, "run_status": run["status"],
                "reimbursement_ids": [r["id"] for r in reimb],
            })
            await db.payroll_employees.insert_one(result)
            for ref in result["rule_refs"]:
                rule_refs[ref["id"]] = ref
            totals["gross"] += result["gross_earnings"]
            totals["net"] += result["net_pay"]
            totals["deductions"] += result["total_deductions"]
            totals["employer_cost"] += result["employer_cost"]
            totals["headcount"] += 1
        except (RuleUnavailable, ValueError) as exc:
            totals["errors"] += 1
            await db.payroll_employees.insert_one({
                "id": new_id(),
                "run_id": run_id, "org_id": org["id"], "fy": fy_label, "period": period,
                "employee_id": emp["id"], "status": "error", "error_reason": str(exc),
                "employee_snapshot": {"name": emp.get("name"), "employee_code": emp.get("employee_code"),
                                      "department": emp.get("department_name")},
                "earnings": [], "deductions": [], "employer_contributions": [],
                "gross_earnings": 0, "net_pay": 0, "total_deductions": 0,
                "total_employer_contributions": 0, "employer_cost": 0, "taxable_gross": 0,
                "paid_days": 0, "lop_days": 0, "total_days": 0, "rule_refs": [],
                "computed_with_unverified_rules": False,
            })
        except Exception:
            totals["errors"] += 1
            logger.exception("payroll calculation crashed for employee %s", emp.get("id"))
            await db.payroll_employees.insert_one({
                "id": new_id(),
                "run_id": run_id, "org_id": org["id"], "fy": fy_label, "period": period,
                "employee_id": emp["id"], "status": "error",
                "error_reason": "Internal calculation error — see server logs",
                "employee_snapshot": {"name": emp.get("name"), "employee_code": emp.get("employee_code")},
                "earnings": [], "deductions": [], "employer_contributions": [],
                "gross_earnings": 0, "net_pay": 0, "total_deductions": 0,
                "total_employer_contributions": 0, "employer_cost": 0, "taxable_gross": 0,
                "paid_days": 0, "lop_days": 0, "total_days": 0, "rule_refs": [],
                "computed_with_unverified_rules": False,
            })

    # Controlled concurrent fan-out (bounded) — never blocks the HTTP request loop unfairly
    sem = asyncio.Semaphore(8)

    async def bounded(emp: dict) -> None:
        async with sem:
            await compute_one(emp)

    await asyncio.gather(*(bounded(e) for e in employees))

    totals = {k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()}
    await db.payroll_runs.update_one(
        {"id": run_id},
        {"$set": {"status": "calculated", "totals": totals, "rule_refs": list(rule_refs.values()),
                  "calculated_at": now(), "job": {"status": "done", "finished_at": now()}}},
    )
    updated = await db.payroll_runs.find_one({"id": run_id}, {"_id": 0})
    await emit(org["id"], "payroll.calculated", actor=actor, entity="payroll_run", entity_id=run_id,
               summary=f"Payroll for {period} calculated: {totals['headcount']} employees, "
                       f"{totals['errors']} error(s)",
               data={"run_id": run_id, "period": period, "totals": totals})
    return updated
