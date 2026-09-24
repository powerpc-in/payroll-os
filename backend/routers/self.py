"""Employee self-service — everything an employee (or a manager) needs, scoped to
their own records only."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lib.auth import Context, get_ctx, new_id
from lib.db import db
from routers.tax import DeclarationsIn, _empty_declarations, _resolve_fy
from services import payroll_engine
from services.payroll_engine import mask_account, mask_pan
from services.payslips import build_payslip
from services.tax_year_profiles import upsert_declarations

router = APIRouter(prefix="/v1/me", tags=["Self-service"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def _own_employee_id(ctx: Context) -> str:
    emp_id = ctx.user.get("employee_id")
    if not emp_id:
        raise HTTPException(status_code=400, detail="Your login is not linked to an employee record")
    return emp_id


async def _me(ctx: Context) -> dict:
    emp_id = ctx.user.get("employee_id")
    if not emp_id:
        raise HTTPException(status_code=400, detail="Your login is not linked to an employee record")
    emp = await db.employees.find_one({"id": emp_id, "org_id": ctx.org_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee record not found in this organisation")
    return emp


def _mask(doc: dict) -> dict:
    if doc.get("pan"):
        doc["pan"] = mask_pan(doc["pan"])
    if doc.get("bank_account"):
        doc["bank_account"] = mask_account(doc["bank_account"])
    if doc.get("aadhaar"):
        doc["aadhaar"] = mask_account(doc["aadhaar"])
    return doc


@router.get("/profile")
async def profile(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    assignment = await db.salary_assignments.find_one(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "active": True}, {"_id": 0})
    structure = None
    if assignment:
        structure = await db.salary_structures.find_one(
            {"id": assignment["structure_id"]}, {"_id": 0})
    return {"employee": _mask(emp), "assignment": assignment, "structure": structure}


@router.get("/payslips")
async def payslips(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    rows = await db.payroll_employees.find(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "run_status": "locked", "status": "ok"},
        {"_id": 0, "run_id": 1, "period": 1, "gross_earnings": 1, "total_deductions": 1,
         "net_pay": 1, "tds_amount": 1, "paid_days": 1, "lop_days": 1, "total_days": 1},
    ).sort("period", -1).to_list(36)
    return rows


@router.get("/payslips/{run_id}")
async def payslip_pdf(run_id: str, ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id, "status": "locked"})
    if not run:
        raise HTTPException(status_code=404, detail="Payslip not available")
    row = await db.payroll_employees.find_one(
        {"run_id": run_id, "employee_id": emp["id"], "org_id": ctx.org_id})
    if not row or row.get("status") != "ok":
        raise HTTPException(status_code=404, detail="No payslip for this period")
    org = await db.organisations.find_one({"id": ctx.org_id}, {"_id": 0})
    pdf_bytes = build_payslip(org or {}, run, row)
    return StreamingResponse(
        iter([pdf_bytes]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip-{run["period"]}.pdf"'})


@router.get("/tax/compare")
async def tax_compare(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    org = await db.organisations.find_one({"id": ctx.org_id}, {"_id": 0})
    from routers.tax import _comparison
    from lib.dates import today_iso
    return await _comparison(org, emp, today_iso()[:7])


@router.get("/tax/declarations")
async def tax_declarations(ctx: Context = Depends(get_ctx), financial_year: str | None = None):
    emp = await _me(ctx)
    fy = _resolve_fy(financial_year)
    doc = await db.tax_year_declarations.find_one(
        {"org_id": ctx.org_id, "employee_id": emp["id"], "financial_year": fy},
        {"_id": 0, "org_id": 0})
    return doc or _empty_declarations(fy)


@router.put("/tax/declarations")
async def save_tax_declarations(input: DeclarationsIn, ctx: Context = Depends(get_ctx),
                                financial_year: str | None = None):
    emp = await _me(ctx)
    fy = _resolve_fy(financial_year)
    doc = await upsert_declarations(ctx.org_id, emp["id"], fy, input, ctx.user)
    doc.pop("org_id", None)
    return doc


@router.get("/leave/balances")
async def leave_balances(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    docs = await db.leave_balances.find({"org_id": ctx.org_id, "employee_id": emp["id"]},
                                        {"_id": 0}).to_list(20)
    return docs


@router.get("/leave/requests")
async def leave_requests(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    docs = await db.leave_requests.find({"org_id": ctx.org_id, "employee_id": emp["id"]},
                                        {"_id": 0}).sort("created_at", -1).to_list(100)
    return docs


class LeaveApply(BaseModel):
    leave_type_id: str
    from_date: str
    to_date: str
    days: float
    reason: str | None = None


@router.post("/leave/requests")
async def apply_leave(input: LeaveApply, ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    from routers.leave import LeaveRequestIn
    from lib.rbac import has_permission
    req_in = LeaveRequestIn(
        employee_id=emp["id"], leave_type_id=input.leave_type_id,
        from_date=input.from_date, to_date=input.to_date, days=input.days, reason=input.reason)
    # Employees use the shared request flow — create directly with role forced to EMPLOYEE semantics
    lt = await db.leave_types.find_one({"id": input.leave_type_id, "org_id": ctx.org_id})
    if not lt:
        raise HTTPException(status_code=404, detail="Leave type not found")
    doc = {
        "id": "", "org_id": ctx.org_id, "employee_id": emp["id"], "employee_name": emp["name"],
        "leave_type_id": lt["id"], "leave_code": lt["code"], "leave_name": lt["name"],
        "paid": lt["paid"], "unpaid": not lt["paid"], "from_date": input.from_date,
        "to_date": input.to_date, "days": input.days, "reason": input.reason,
        "status": "pending", "created_at": now(), "decided_by": None, "decided_at": None,
    }
    doc["id"] = new_id()
    await db.leave_requests.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/attendance")
async def attendance(ctx: Context = Depends(get_ctx), period: str | None = None):
    emp = await _me(ctx)
    query: dict = {"org_id": ctx.org_id, "employee_id": emp["id"]}
    if period:
        query["period"] = period
    docs = await db.attendance.find(query, {"_id": 0}).sort("date", -1).to_list(62)
    return docs


@router.get("/loans")
async def loans(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    docs = await db.loans.find({"org_id": ctx.org_id, "employee_id": emp["id"]},
                               {"_id": 0}).sort("created_at", -1).to_list(50)
    return docs


@router.get("/reimbursements")
async def reimbursements(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    docs = await db.reimbursements.find({"org_id": ctx.org_id, "employee_id": emp["id"]},
                                        {"_id": 0}).sort("created_at", -1).to_list(100)
    return docs


@router.get("/documents")
async def documents(ctx: Context = Depends(get_ctx)):
    emp = await _me(ctx)
    docs = await db.documents.find(
        {"org_id": ctx.org_id, "employee_id": emp["id"]},
        {"_id": 0, "data": 0}).sort("created_at", -1).to_list(100)
    return docs
