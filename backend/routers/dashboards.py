"""Role-aware dashboards and analytics — every figure comes from live database
aggregates, never mocked."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lib.auth import Context, require_perm
from lib.db import db
from lib.dates import today_iso

router = APIRouter(prefix="/v1", tags=["Dashboards"])


async def _latest_run(org_id: str) -> dict | None:
    return await db.payroll_runs.find_one({"org_id": org_id}, {"_id": 0}, sort=[("period", -1)])


async def _trends(org_id: str, months: int = 6) -> list[dict]:
    runs = await db.payroll_runs.find(
        {"org_id": org_id, "status": {"$in": ["calculated", "review", "approved", "locked"]}},
        {"_id": 0, "period": 1, "totals": 1}).sort("period", -1).to_list(months)
    runs.reverse()
    return [{"period": r["period"], **(r.get("totals") or {})} for r in runs]


async def _dept_breakdown(org_id: str, run: dict | None) -> list[dict]:
    if not run:
        return []
    rows = await db.payroll_employees.find({"run_id": run["id"], "org_id": org_id},
                                           {"_id": 0, "employee_snapshot": 1, "gross_earnings": 1,
                                            "net_pay": 1, "employer_cost": 1}).to_list(5000)
    by_dept: dict[str, dict] = {}
    for r in rows:
        dept = (r.get("employee_snapshot") or {}).get("department") or "Unassigned"
        g = by_dept.setdefault(dept, {"department": dept, "gross": 0, "net": 0, "headcount": 0})
        g["gross"] = round(g["gross"] + r.get("gross_earnings", 0), 2)
        g["net"] = round(g["net"] + r.get("net_pay", 0), 2)
        g["headcount"] += 1
    return sorted(by_dept.values(), key=lambda x: -x["gross"])


@router.get("/dashboards")
async def dashboard(ctx: Context = Depends(require_perm("dashboards.view"))):
    org_id = ctx.org_id
    org = await db.organisations.find_one({"id": org_id}, {"_id": 0})
    period = today_iso()[:7]

    if ctx.role == "EMPLOYEE":
        emp_id = ctx.user.get("employee_id")
        payload: dict = {"role": ctx.role, "org": org, "period": period, "employee": None}
        if not emp_id:
            payload["notice"] = "Your login is not yet linked to an employee record."
            return payload
        emp = await db.employees.find_one({"id": emp_id, "org_id": ctx.org_id}, {"_id": 0})
        rows = await db.payroll_employees.find(
            {"org_id": org_id, "employee_id": emp_id, "status": "ok"},
            {"_id": 0}).sort("period", -1).to_list(24)
        latest = rows[0] if rows else None
        ytd = {"gross": round(sum(r.get("gross_earnings", 0) for r in rows), 2),
               "net": round(sum(r.get("net_pay", 0) for r in rows), 2),
               "tds": round(sum(r.get("tds_amount", 0) for r in rows), 2),
               "pf": round(sum(r.get("pf_employee", 0) for r in rows), 2)}
        balances = await db.leave_balances.find({"org_id": org_id, "employee_id": emp_id},
                                                {"_id": 0}).to_list(20)
        att = await db.attendance.find({"org_id": org_id, "employee_id": emp_id, "period": period},
                                       {"_id": 0, "status": 1, "days": 1}).to_list(40)
        payload["employee"] = {"profile": emp, "latest_payslip": latest, "ytd": ytd,
                               "leave_balances": balances, "attendance_this_month": att,
                               "payslip_ready": bool(latest and latest.get("run_status") == "locked")}
        return payload

    headcount = await db.employees.count_documents({"org_id": org_id, "status": "active"})
    exited = await db.employees.count_documents({"org_id": org_id, "status": "exited"})
    month_start = f"{period}-01"
    joiners = await db.employees.count_documents(
        {"org_id": org_id, "joining_date": {"$gte": month_start}})
    run = await _latest_run(org_id)
    dept_cost = await _dept_breakdown(org_id, run)
    pending_leave = await db.leave_requests.count_documents({"org_id": org_id, "status": "pending"})
    pending_reimb = await db.reimbursements.count_documents({"org_id": org_id, "status": "pending"})
    unverified_rules = await db.statutory_rules.count_documents(
        {"jurisdiction": (org or {}).get("jurisdiction", "IN"), "verified": False})
    missing_salary = await db.salary_assignments.count_documents({"org_id": org_id, "active": True}) < headcount
    errors_in_run = (run.get("totals", {}).get("errors", 0) if run else 0)

    return {
        "role": ctx.role, "org": org, "period": period,
        "headcount": headcount, "exits": exited, "new_joiners": joiners,
        "latest_run": run, "dept_cost": dept_cost, "trends": await _trends(org_id),
        "pending": {"leave": pending_leave, "reimbursements": pending_reimb},
        "compliance_alerts": {
            "unverified_rules": unverified_rules,
            "missing_salary_assignments": missing_salary,
            "run_errors": errors_in_run,
        },
    }


@router.get("/analytics")
async def analytics(ctx: Context = Depends(require_perm("dashboards.view"))):
    org_id = ctx.org_id
    trends = await _trends(org_id, 12)
    runs = await db.payroll_runs.find({"org_id": org_id, "status": {"$in": ["calculated", "review", "approved", "locked"]}},
                                      {"_id": 0, "period": 1, "totals": 1}).sort("period", -1).to_list(12)

    assignments = await db.salary_assignments.find({"org_id": org_id, "active": True},
                                                   {"_id": 0, "gross_monthly": 1}).to_list(5000)
    grosses = sorted((a["gross_monthly"] for a in assignments), reverse=True)
    buckets = []
    if grosses:
        edges = [0, 25000, 50000, 75000, 100000, 150000, 10**9]
        labels = ["<25k", "25–50k", "50–75k", "75k–1L", "1–1.5L", ">1.5L"]
        for label, lo, hi in zip(labels, edges, edges[1:]):
            buckets.append({"band": label, "employees": sum(1 for g in grosses if lo <= g < hi)})

    emps = await db.employees.find({}, {"_id": 0, "department_name": 1, "status": 1,
                                        "joining_date": 1, "exit_date": 1}).to_list(5000)
    active_emps = [e for e in emps if e.get("status") == "active"]
    by_dept: dict[str, int] = {}
    for e in active_emps:
        d = e.get("department_name") or "Unassigned"
        by_dept[d] = by_dept.get(d, 0) + 1

    reimb_rows = await db.reimbursements.find({"org_id": org_id}, {"_id": 0, "date": 1, "approved_amount": 1}).to_list(2000)
    reimb_trend: dict[str, float] = {}
    for r in reimb_rows:
        if r.get("date"):
            m = r["date"][:7]
            reimb_trend[m] = round(reimb_trend.get(m, 0) + (r.get("approved_amount") or 0), 2)

    leave_types = await db.leave_types.find({"org_id": org_id}, {"_id": 0}).to_list(20)
    balances = await db.leave_balances.find({"org_id": org_id}, {"_id": 0}).to_list(5000)
    util: dict[str, dict] = {}
    for b in balances:
        u = util.setdefault(b.get("leave_code", "?"), {"leave": b.get("leave_code", "?"), "granted": 0, "used": 0})
        u["granted"] += b.get("granted", 0)
        u["used"] += b.get("used", 0)
    leave_util = [{"leave": u["leave"],
                   "utilisation_pct": round(u["used"] / u["granted"] * 100, 1) if u["granted"] else 0}
                  for u in util.values()]

    return {
        "payroll_trend": trends,
        "salary_distribution": buckets,
        "department_headcount": [{"department": k, "headcount": v} for k, v in sorted(by_dept.items(), key=lambda x: -x[1])],
        "reimbursement_trend": [{"period": k, "approved": v} for k, v in sorted(reimb_trend.items())],
        "leave_utilisation": leave_util,
        "leave_types": leave_types,
        "runs": runs,
    }
