"""Reporting engine — reusable dataset definitions + filters/grouping/aggregation +
CSV/Excel/PDF export, plus saved (custom) reports. No hard-coded report strings
in the UI: the frontend renders whatever this engine defines."""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lib.auth import Context, new_id, require_perm
from lib.db import db

router = APIRouter(prefix="/v1/reports", tags=["Reports"])


def _f(key: str, label: str, numeric: bool = False) -> dict:
    return {"key": key, "label": label, "numeric": numeric}


def _pay_fields(extra: list[dict] | None = None) -> list[dict]:
    base = [
        _f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
        _f("department", "Department"), _f("location", "Location"),
        _f("gross_earnings", "Gross", True), _f("total_deductions", "Deductions", True),
    ]
    return base + (extra or [])


DATASETS: dict[str, dict] = {
    "payroll_register": {"name": "Payroll Register", "collection": "payroll_employees", "time_field": "period",
                         "fields": _pay_fields([_f("net_pay", "Net Pay", True), _f("employer_cost", "Employer Cost", True)])},
    "tds": {"name": "TDS", "collection": "payroll_employees", "time_field": "period",
            "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                       _f("taxable_gross", "Taxable Gross", True), _f("tds_amount", "TDS", True), _f("fy", "Financial Year")]},
    "pf": {"name": "Provident Fund", "collection": "payroll_employees", "time_field": "period",
           "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                      _f("pf_employee", "Employee PF", True), _f("pf_employer", "Employer PF", True)]},
    "esi": {"name": "ESI", "collection": "payroll_employees", "time_field": "period",
            "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                       _f("esi_employee", "Employee ESI", True), _f("esi_employer", "Employer ESI", True)]},
    "pt": {"name": "Professional Tax", "collection": "payroll_employees", "time_field": "period",
           "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                      _f("state", "State"), _f("pt_amount", "PT", True)]},
    "lwf": {"name": "Labour Welfare Fund", "collection": "payroll_employees", "time_field": "period",
            "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                       _f("state", "State"), _f("lwf_amount", "LWF", True)]},
    "employer_contributions": {"name": "Employer Contributions", "collection": "payroll_employees",
                               "time_field": "period",
                               "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"),
                                          _f("employee_name", "Employee"), _f("pf_employer", "Employer PF", True),
                                          _f("esi_employer", "Employer ESI", True),
                                          _f("total_employer_contributions", "Total Contributions", True),
                                          _f("employer_cost", "Employer Cost", True)]},
    "net_pay": {"name": "Net Pay", "collection": "payroll_employees", "time_field": "period",
                "fields": _pay_fields([_f("tds_amount", "TDS", True), _f("net_pay", "Net Pay", True)])},
    "employee_earnings": {"name": "Employee Earnings (by component)", "collection": "payroll_employees",
                          "time_field": "period", "flatten": ("earnings",),
                          "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"),
                                     _f("employee_name", "Employee"), _f("component", "Component"),
                                     _f("amount", "Amount", True)]},
    "employee_deductions": {"name": "Employee Deductions (by component)", "collection": "payroll_employees",
                            "time_field": "period", "flatten": ("deductions",),
                            "fields": [_f("period", "Period"), _f("employee_code", "Employee ID"),
                                       _f("employee_name", "Employee"), _f("component", "Component"),
                                       _f("amount", "Amount", True)]},
    "ctc": {"name": "CTC (annual, from assignments)", "collection": "salary_assignments", "time_field": None,
            "fields": [_f("employee_code", "Employee ID"), _f("employee_name", "Employee"),
                       _f("department", "Department"), _f("gross_monthly", "Gross / month", True),
                       _f("annual_ctc", "Annual CTC", True)]},
    "department_payroll": {"name": "Department Payroll", "collection": "payroll_employees",
                           "time_field": "period", "group_only": "department",
                           "fields": [_f("group", "Department"), _f("headcount", "Employees", True),
                                      _f("gross_earnings", "Gross", True), _f("net_pay", "Net Pay", True),
                                      _f("employer_cost", "Employer Cost", True)]},
    "location_payroll": {"name": "Location Payroll", "collection": "payroll_employees",
                         "time_field": "period", "group_only": "location",
                         "fields": [_f("group", "Location"), _f("headcount", "Employees", True),
                                    _f("gross_earnings", "Gross", True), _f("net_pay", "Net Pay", True),
                                    _f("employer_cost", "Employer Cost", True)]},
    "cost_centre_payroll": {"name": "Cost Centre Payroll", "collection": "payroll_employees",
                            "time_field": "period", "group_only": "cost_centre",
                            "fields": [_f("group", "Cost Centre"), _f("headcount", "Employees", True),
                                       _f("gross_earnings", "Gross", True), _f("net_pay", "Net Pay", True),
                                       _f("employer_cost", "Employer Cost", True)]},
    "reimbursements": {"name": "Reimbursements", "collection": "reimbursements", "time_field": None,
                       "fields": [_f("date", "Date"), _f("employee_name", "Employee"),
                                  _f("category", "Category"), _f("amount", "Claimed", True),
                                  _f("approved_amount", "Approved", True), _f("status", "Status")]},
    "loans": {"name": "Loans & Advances", "collection": "loans", "time_field": None,
              "fields": [_f("employee_name", "Employee"), _f("name", "Loan"), _f("principal", "Principal", True),
                         _f("emi", "EMI", True), _f("outstanding", "Outstanding", True),
                         _f("interest_rate", "Interest %", True), _f("status", "Status")]},
    "ff": {"name": "Full & Final Settlements", "collection": "ffs", "time_field": None,
           "fields": [_f("employee_name", "Employee"), _f("last_working_day", "LWD"),
                      _f("total_payable", "Payable", True), _f("total_recoveries", "Recoveries", True),
                      _f("net_settlement", "Net Settlement", True), _f("status", "Status")]},
}


class ReportRun(BaseModel):
    dataset: str
    period_from: str | None = None
    period_to: str | None = None
    department: str | None = None
    location: str | None = None
    group_by: str | None = None
    sort_by: str | None = None
    sort_dir: str = "asc"
    limit: int = 500


async def _rows_for(ctx: Context, cfg: dict, r: ReportRun) -> list[dict]:
    collection = db[cfg["collection"]]
    query: dict = {"org_id": ctx.org_id}
    time_field = cfg.get("time_field")
    if time_field:
        rng: dict = {}
        if r.period_from:
            rng["$gte"] = r.period_from
        if r.period_to:
            rng["$lte"] = r.period_to
        if rng:
            query[time_field] = rng
    docs = await collection.find(query).to_list(r.limit * 4 + 1000)

    flat = cfg.get("flatten")
    rows: list[dict] = []
    if flat:
        for d in docs:
            snap = dict(d.get("employee_snapshot") or {})
            base = {"period": d.get("period"), "employee_code": snap.get("employee_code"),
                    "employee_name": snap.get("name"), "department": snap.get("department"),
                    "location": snap.get("location")}
            for item in d.get(flat[0], []):
                row = dict(base)
                row["component"] = f"{item.get('code', '')} · {item.get('name', '')}"
                row["amount"] = item.get("amount", 0)
                rows.append(row)
    elif cfg["collection"] == "payroll_employees":
        for d in docs:
            snap = dict(d.pop("employee_snapshot", {}) or {})
            d.update(snap)
            d["employee_name"] = snap.get("name")
            rows.append(d)
    elif cfg["collection"] == "salary_assignments":
        active = [d for d in docs if d.get("active", True)]
        emps = {e["id"]: e for e in await db.employees.find(
            {"org_id": ctx.org_id, "id": {"$in": [a["employee_id"] for a in active]}}).to_list(5000)}
        for a in active:
            e = emps.get(a["employee_id"], {})
            rows.append({
                "employee_code": e.get("employee_code"), "employee_name": e.get("name"),
                "department": e.get("department_name"), "gross_monthly": a.get("gross_monthly"),
                "annual_ctc": round((a.get("gross_monthly") or 0) * 12, 2),
            })
    elif cfg["collection"] == "attendance":
        summary: dict[str, dict] = {}
        for d in docs:
            entry = summary.setdefault(d["employee_id"], {
                "present": 0.0, "absent": 0.0, "half_day": 0.0, "paid_leave": 0.0,
                "unpaid_leave": 0.0, "overtime_hours": 0.0})
            st = d.get("status")
            if st in entry and st != "overtime_hours":
                entry[st] += d.get("days", 1)
            entry["overtime_hours"] += d.get("overtime_hours", 0) or 0
        emps = {e["id"]: e for e in await db.employees.find(
            {"org_id": ctx.org_id, "id": {"$in": list(summary.keys())}}).to_list(5000)}
        for emp_id, e in summary.items():
            emp = emps.get(emp_id, {})
            rows.append({
                "employee_code": emp.get("employee_code"), "employee_name": emp.get("name"),
                **e, "lop": e["absent"] + e["unpaid_leave"] + 0.5 * e["half_day"],
            })
        if not r.sort_by:
            rows.sort(key=lambda x: x.get("employee_name") or "")
    else:
        rows = docs

    if r.department:
        rows = [x for x in rows if x.get("department") == r.department]
    if r.location:
        rows = [x for x in rows if x.get("location") == r.location]
    return rows


def _project(rows: list[dict], cfg: dict, r: ReportRun) -> tuple[list[str], list[dict], dict]:
    fields = cfg["fields"]
    if cfg.get("group_only"):
        r.group_by = cfg["group_only"]
    if r.group_by:
        grouped: dict[str, dict] = {}
        for row in rows:
            key = str(row.get(r.group_by) or "—")
            g = grouped.setdefault(key, {"group": key, "headcount": 0,
                                         **{f["key"]: 0.0 for f in fields if f["numeric"] and f["key"] != "headcount"}})
            g["headcount"] += 1
            for f in fields:
                if f["numeric"] and f["key"] != "headcount":
                    g[f["key"]] = round(g[f["key"]] + (row.get(f["key"]) or 0), 2)
        out = list(grouped.values())
        columns = [f["key"] for f in fields]
        totals = {f["key"]: round(sum(x.get(f["key"], 0) for x in out), 2)
                  for f in fields if f["numeric"]}
        return columns, out, totals

    keys = [f["key"] for f in fields]
    out = [{k: row.get(k) for k in keys} for row in rows]
    if r.sort_by:
        out.sort(key=lambda x: (x.get(r.sort_by) is None, x.get(r.sort_by)),
                 reverse=r.sort_dir == "desc")
    totals = {f["key"]: round(sum(x.get(f["key"]) or 0 for x in out if isinstance(x.get(f["key"]), (int, float))), 2)
              for f in fields if f["numeric"]}
    return keys, out[: r.limit], totals


def _export_response(columns: list[str], rows: list[dict], fmt: str, name: str):
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(columns)
        for row in rows:
            ws.append([row.get(c) for c in columns])
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        return StreamingResponse(iter([bio.getvalue()]),
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    if fmt == "pdf":
        from fpdf import FPDF
        pdf = FPDF(orientation="L", format="A4")
        pdf.add_page()
        pdf.set_font("Helvetica", size=8)
        pdf.cell(0, 6, name, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=6.5)
        pdf.cell(0, 4, datetime.now(timezone.utc).strftime("Generated %Y-%m-%d %H:%M UTC"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        col_w = 270 / max(1, len(columns))
        pdf.set_fill_color(241, 245, 249)
        for c in columns:
            pdf.cell(col_w, 5, str(c)[:28], border=1, fill=True)
        pdf.ln()
        for row in rows[:400]:
            for c in columns:
                v = row.get(c, "")
                if isinstance(v, float):
                    text = f"{v:,.2f}"
                else:
                    text = str(v if v is not None else "")[:28]
                pdf.cell(col_w, 5, text, border=1)
            pdf.ln()
        return StreamingResponse(iter([bytes(pdf.output())]), media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    raise HTTPException(status_code=422, detail="format must be csv, xlsx or pdf")


@router.get("/datasets")
async def datasets(ctx: Context = Depends(require_perm("reports.view"))):
    return [{"key": k, "name": v["name"],
             "fields": v["fields"], "time_field": v.get("time_field"),
             "group_only": v.get("group_only"), "flatten": bool(v.get("flatten"))}
            for k, v in DATASETS.items()]


@router.post("/run")
async def run_report(r: ReportRun, ctx: Context = Depends(require_perm("reports.view"))):
    cfg = DATASETS.get(r.dataset)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown dataset '{r.dataset}'")
    rows = await _rows_for(ctx, cfg, r)
    columns, out, totals = _project(rows, cfg, r)
    return {"dataset": r.dataset, "name": cfg["name"], "columns": columns,
            "labels": {f["key"]: f["label"] for f in cfg["fields"]},
            "rows": out, "totals": totals, "count": len(out)}


@router.post("/export")
async def export_report(r: ReportRun, format: str = "csv",
                        ctx: Context = Depends(require_perm("reports.export"))):
    cfg = DATASETS.get(r.dataset)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Unknown dataset '{r.dataset}'")
    rows = await _rows_for(ctx, cfg, r)
    columns, out, _ = _project(rows, cfg, r)
    return _export_response(columns, out, format, cfg["name"])


class SavedReportIn(BaseModel):
    name: str
    config: dict


@router.get("/saved")
async def list_saved(ctx: Context = Depends(require_perm("reports.view"))):
    docs = await db.saved_reports.find({"org_id": ctx.org_id}).sort("created_at", -1).to_list(100)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/saved")
async def save_report(input: SavedReportIn, ctx: Context = Depends(require_perm("reports.manage"))):
    doc = {"id": new_id(), "org_id": ctx.org_id, "name": input.name, "config": input.config,
           "created_by": ctx.user["email"], "created_at": datetime.now(timezone.utc)}
    await db.saved_reports.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/saved/{saved_id}")
async def delete_saved(saved_id: str, ctx: Context = Depends(require_perm("reports.manage"))):
    await db.saved_reports.delete_one({"id": saved_id, "org_id": ctx.org_id})
    return {"ok": True}
