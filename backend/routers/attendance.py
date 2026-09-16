"""Attendance — statuses feed payroll (LOP), supports CSV import."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1", tags=["Attendance"])

STATUSES = ["present", "absent", "half_day", "paid_leave", "unpaid_leave", "weekly_off", "holiday"]


def now() -> datetime:
    return datetime.now(timezone.utc)


class AttendanceIn(BaseModel):
    employee_id: str
    date: str  # YYYY-MM-DD
    status: str
    days: float = Field(default=1, gt=0, le=1)
    overtime_hours: float = Field(default=0, ge=0, le=24)


class ImportIn(BaseModel):
    rows: list[AttendanceIn]


@router.get("/attendance")
async def list_attendance(ctx: Context = Depends(require_perm("attendance.view")),
                          employee_id: str | None = None, period: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    if period:
        query["period"] = period
    docs = await db.attendance.find(query).sort("date", -1).to_list(1000)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/attendance")
async def upsert_attendance(input: AttendanceIn, ctx: Context = Depends(require_perm("attendance.manage"))):
    if input.status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {STATUSES}")
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    period = input.date[:7]
    existing = await db.attendance.find_one(
        {"org_id": ctx.org_id, "employee_id": input.employee_id, "date": input.date})
    if existing:
        await db.attendance.update_one(
            {"id": existing["id"]},
            {"$set": {"status": input.status, "days": input.days,
                      "overtime_hours": input.overtime_hours, "period": period}})
    else:
        await db.attendance.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "employee_id": input.employee_id,
            "date": input.date, "status": input.status, "days": input.days,
            "overtime_hours": input.overtime_hours, "period": period,
        })
    return {"ok": True}


@router.post("/attendance/import")
async def import_attendance(input: ImportIn, ctx: Context = Depends(require_perm("attendance.manage"))):
    """Validates every row first; valid rows are imported, invalid rows are returned
    with reasons so failures are clearly identified (spec §29)."""
    errors: list[dict] = []
    imported = 0
    emp_cache: dict[str, bool] = {}
    for i, row in enumerate(input.rows):
        row_errors: list[str] = []
        if row.status not in STATUSES:
            row_errors.append(f"invalid status '{row.status}'")
        if row.employee_id not in emp_cache:
            emp_cache[row.employee_id] = bool(await db.employees.find_one(
                {"id": row.employee_id, "org_id": ctx.org_id}))
        if not emp_cache[row.employee_id]:
            row_errors.append("employee not found in this organisation")
        if len(row.date) != 10:
            row_errors.append("date must be YYYY-MM-DD")
        if row_errors:
            errors.append({"row": i + 1, "errors": row_errors})
            continue
        existing = await db.attendance.find_one(
            {"org_id": ctx.org_id, "employee_id": row.employee_id, "date": row.date})
        if existing:
            await db.attendance.update_one(
                {"id": existing["id"]},
                {"$set": {"status": row.status, "days": row.days, "overtime_hours": row.overtime_hours,
                          "period": row.date[:7]}})
        else:
            await db.attendance.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "employee_id": row.employee_id,
                "date": row.date, "status": row.status, "days": row.days,
                "overtime_hours": row.overtime_hours, "period": row.date[:7],
            })
        imported += 1
    await emit(ctx.org_id, "attendance.imported", actor=ctx.user, entity="attendance",
               summary=f"Attendance import: {imported} rows imported, {len(errors)} rejected")
    return {"imported": imported, "errors": errors, "total": len(input.rows)}


@router.get("/attendance/summary")
async def attendance_summary(period: str, ctx: Context = Depends(require_perm("attendance.view"))):
    docs = await db.attendance.find({"org_id": ctx.org_id, "period": period}).to_list(20000)
    by_emp: dict[str, dict] = {}
    for d in docs:
        entry = by_emp.setdefault(d["employee_id"], {
            "employee_id": d["employee_id"], "present": 0, "absent": 0, "half_day": 0,
            "paid_leave": 0, "unpaid_leave": 0, "weekly_off": 0, "holiday": 0,
            "overtime_hours": 0,
        })
        status = d.get("status")
        if status in ("present", "absent", "paid_leave", "unpaid_leave", "weekly_off", "holiday"):
            entry[status] += d.get("days", 1)
        elif status == "half_day":
            entry["half_day"] += d.get("days", 1)
        entry["overtime_hours"] += d.get("overtime_hours", 0) or 0
    names = {e["id"]: e for e in await db.employees.find(
        {"org_id": ctx.org_id, "id": {"$in": list(by_emp.keys())}},
        {"id": 1, "name": 1, "employee_code": 1}).to_list(5000)}
    result = []
    for entry in by_emp.values():
        emp = names.get(entry["employee_id"], {})
        entry["name"] = emp.get("name", "Unknown")
        entry["employee_code"] = emp.get("employee_code", "")
        entry["lop"] = entry["absent"] + entry["unpaid_leave"] + 0.5 * entry["half_day"]
        result.append(entry)
    result.sort(key=lambda x: x["name"])
    return result
