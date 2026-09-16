"""Payroll runs — the workflow: DRAFT → CALCULATED → REVIEW → APPROVED → LOCKED.

Every transition is permission-guarded, audited and webhook-emitted. Payslip PDFs
are rendered on demand; a locked run is immutable history tied to the rule
versions snapshot at calculation time."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from services import payroll_service
from services.payslips import build_payslip

router = APIRouter(prefix="/v1/payroll", tags=["Payroll"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class RunCreate(BaseModel):
    period: str  # YYYY-MM


class InputIn(BaseModel):
    employee_id: str
    input_type: str  # bonus | overtime | arrear | adjustment | deduction
    amount: float = Field(gt=0)
    note: str | None = None
    taxable: bool = True


@router.get("/runs")
async def list_runs(ctx: Context = Depends(require_perm("payroll.view")),
                    page: int = Query(1, ge=1), limit: int = Query(12, ge=1, le=50),
                    status: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if status:
        query["status"] = status
    total = await db.payroll_runs.count_documents(query)
    docs = await db.payroll_runs.find(query).sort("period", -1).skip((page - 1) * limit) \
        .limit(limit).to_list(limit)
    for d in docs:
        d.pop("_id", None)
    return {"items": docs, "total": total, "page": page, "limit": limit}


@router.post("/runs")
async def create_run(input: RunCreate, ctx: Context = Depends(require_perm("payroll.calculate"))):
    if len(input.period) != 7 or input.period[4] != "-":
        raise HTTPException(status_code=422, detail="period must be YYYY-MM")
    org = await db.organisations.find_one({"id": ctx.org_id})
    try:
        run = await payroll_service.create_run(org, input.period, ctx.user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    run.pop("_id", None)
    return run


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: Context = Depends(require_perm("payroll.view")),
                  page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  q: str | None = None):
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    query: dict = {"run_id": run_id, "org_id": ctx.org_id}
    if q:
        query["employee_snapshot.name"] = {"$regex": q, "$options": "i"}
    total = await db.payroll_employees.count_documents(query)
    rows = await db.payroll_employees.find(query).sort("employee_snapshot.name", 1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit)
    for r in rows:
        r.pop("_id", None)
    return {"run": run, "rows": rows, "total": total, "page": page, "limit": limit}


@router.post("/runs/{run_id}/calculate")
async def calculate(run_id: str, ctx: Context = Depends(require_perm("payroll.calculate"))):
    """Runs as a bounded-concurrency backend job; results are persisted before the
    run transitions to CALCULATED. Failures are per-employee and fail safe."""
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    try:
        updated = await payroll_service.calculate_run(run_id, ctx.user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await emit(ctx.org_id, "payroll.calculated", actor=ctx.user, entity="payroll_run",
               entity_id=run_id, summary=f"Payroll {run['period']} calculated by {ctx.user['email']}")
    return updated


@router.post("/runs/{run_id}/inputs")
async def add_input(run_id: str, input: InputIn, ctx: Context = Depends(require_perm("payroll.calculate"))):
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] not in ("draft", "calculated", "review"):
        raise HTTPException(status_code=409, detail="Inputs can only be added before approval")
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    if input.input_type not in ("bonus", "overtime", "arrear", "adjustment", "deduction"):
        raise HTTPException(status_code=422, detail="Unknown input type")
    doc = {
        "id": new_id(), "run_id": run_id, "org_id": ctx.org_id, "employee_id": input.employee_id,
        "employee_name": emp["name"], "input_type": input.input_type, "amount": input.amount,
        "note": input.note, "taxable": input.taxable, "created_by": ctx.user["email"],
        "created_at": now(),
    }
    await db.payroll_inputs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/runs/{run_id}/inputs/{input_id}")
async def delete_input(run_id: str, input_id: str, ctx: Context = Depends(require_perm("payroll.calculate"))):
    await db.payroll_inputs.delete_one({"id": input_id, "run_id": run_id, "org_id": ctx.org_id})
    return {"ok": True}


@router.get("/runs/{run_id}/inputs")
async def list_inputs(run_id: str, ctx: Context = Depends(require_perm("payroll.view"))):
    docs = await db.payroll_inputs.find({"run_id": run_id, "org_id": ctx.org_id}) \
        .sort("created_at", -1).to_list(500)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.get("/runs/{run_id}/employees/{employee_id}")
async def run_employee(run_id: str, employee_id: str,
                       ctx: Context = Depends(require_perm("payroll.view"))):
    row = await db.payroll_employees.find_one(
        {"run_id": run_id, "employee_id": employee_id, "org_id": ctx.org_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Employee not part of this run")
    inputs = await db.payroll_inputs.find({"run_id": run_id, "employee_id": employee_id},
                                          {"_id": 0}).to_list(100)
    return {"result": row, "inputs": inputs}


class TransitionIn(BaseModel):
    note: str | None = None


async def _transition(run_id: str, ctx: Context, from_status: str, to_status: str,
                      event: str, perm: str, summary: str) -> dict:
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != from_status:
        raise HTTPException(
            status_code=409,
            detail=f"Run is '{run['status']}' — this action requires '{from_status}'")
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {"status": to_status}})
    await db.payroll_employees.update_many({"run_id": run_id}, {"$set": {"run_status": to_status}})
    await emit(ctx.org_id, event, actor=ctx.user, entity="payroll_run", entity_id=run_id,
               old={"status": from_status}, new={"status": to_status}, summary=summary,
               data={"run_id": run_id, "period": run["period"], "status": to_status})
    return await db.payroll_runs.find_one({"id": run_id}, {"_id": 0})


@router.post("/runs/{run_id}/submit-review")
async def submit_review(run_id: str, ctx: Context = Depends(require_perm("payroll.review"))):
    return await _transition(run_id, ctx, "calculated", "review", "payroll.submitted",
                             "payroll.review", f"Payroll {run_id[:8]} submitted for review")


@router.post("/runs/{run_id}/approve")
async def approve(run_id: str, ctx: Context = Depends(require_perm("payroll.approve"))):
    return await _transition(run_id, ctx, "review", "approved", "payroll.approved",
                             "payroll.approve", f"Payroll {run_id[:8]} approved by {ctx.user['email']}")


@router.post("/runs/{run_id}/lock")
async def lock(run_id: str, ctx: Context = Depends(require_perm("payroll.lock"))):
    run = await _transition(run_id, ctx, "approved", "locked", "payroll.locked",
                            "payroll.lock", f"Payroll {run_id[:8]} locked — payslips available")
    # Side effects of locking: loan repayments land, reimbursements become paid
    rows = await db.payroll_employees.find({"run_id": run_id, "org_id": ctx.org_id}).to_list(2000)
    for row in rows:
        for rid in row.get("reimbursement_ids", []):
            await db.reimbursements.update_one(
                {"id": rid, "org_id": ctx.org_id, "status": "approved"},
                {"$set": {"paid_run_id": run_id, "status": "paid"}})
    loans = await db.loans.find({"org_id": ctx.org_id, "status": "active",
                                 "deduct_from_payroll": True}).to_list(500)
    period = run["period"]
    for loan in loans:
        sched_row = next((r for r in loan.get("schedule", []) if r["period"] == period), None)
        if not sched_row:
            continue
        await db.loan_repayments.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "loan_id": loan["id"],
            "employee_id": loan["employee_id"], "period": period,
            "emi": sched_row["emi"], "principal": sched_row["principal"],
            "interest": sched_row["interest"], "paid_via": f"payroll:{run_id}", "created_at": now(),
        })
        new_outstanding = round(loan["outstanding"] - sched_row["principal"], 2)
        updates = {"outstanding": new_outstanding}
        if new_outstanding <= 0.01:
            updates["status"] = "closed"
            updates["closed_at"] = now()
        await db.loans.update_one({"id": loan["id"]}, {"$set": updates})
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {"payslips_generated": True}})

    # Payslip-ready alert: one event per employee whose login is linked to their record.
    # `emit` records it in-app now and queues the email / PWA-push / mobile-push channels
    # for whenever a provider is configured — the same payload serves all of them.
    emp_ids = [row["employee_id"] for row in rows if row.get("status") == "ok"]
    users = await db.users.find({"memberships.org_id": ctx.org_id,
                                 "employee_id": {"$in": emp_ids}}).to_list(2000)
    by_emp = {u.get("employee_id"): u for u in users}
    for row in rows:
        user = by_emp.get(row["employee_id"])
        if not user:
            continue
        await emit(ctx.org_id, "payslip.generated", actor=ctx.user, entity="payslip",
                   entity_id=f"{run_id}:{row['employee_id']}",
                   summary=f"Your payslip for {period} is ready — net "
                           f"{row.get('net_pay', 0):,.2f}",
                   notify_user_ids=[user["id"]],
                   data={"run_id": run_id, "period": period,
                         "employee_id": row["employee_id"],
                         "employee_code": (row.get("employee_snapshot") or {}).get("employee_code"),
                         "net_pay": row.get("net_pay"),
                         "payslip_url": f"/api/v1/payroll/payslips/{run_id}/{row['employee_id']}"})
    return run


@router.post("/runs/{run_id}/reverse")
async def reverse(run_id: str, input: TransitionIn, ctx: Context = Depends(require_perm("payroll.reverse"))):
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    reverse_to = {"approved": "review", "review": "calculated", "calculated": "draft"}.get(run["status"])
    if not reverse_to:
        raise HTTPException(status_code=409, detail="Locked runs are immutable and cannot be reversed")
    await db.payroll_runs.update_one({"id": run_id}, {"$set": {"status": reverse_to}})
    await db.payroll_employees.update_many({"run_id": run_id}, {"$set": {"run_status": reverse_to}})
    await emit(ctx.org_id, "payroll.reversed", actor=ctx.user, entity="payroll_run", entity_id=run_id,
               old={"status": run["status"]}, new={"status": reverse_to},
               summary=f"Payroll {run['period']} reversed from {run['status']} to {reverse_to}"
                       + (f": {input.note}" if input.note else ""))
    return await db.payroll_runs.find_one({"id": run_id}, {"_id": 0})


@router.get("/payslips/{run_id}/{employee_id}")
async def payslip_pdf(run_id: str, employee_id: str, ctx: Context = Depends(require_perm("payroll.view"))):
    run = await db.payroll_runs.find_one({"id": run_id, "org_id": ctx.org_id})
    if not run:
        raise HTTPException(status_code=404, detail="Payroll run not found")
    if run["status"] != "locked":
        raise HTTPException(status_code=409, detail="Payslips are available once the run is locked")
    return await _pdf_response(ctx.org_id, run, employee_id)


async def _pdf_response(org_id: str, run: dict, employee_id: str):
    row = await db.payroll_employees.find_one(
        {"run_id": run["id"], "employee_id": employee_id, "org_id": org_id})
    if not row or row.get("status") != "ok":
        raise HTTPException(status_code=404, detail="No calculated payroll for this employee in this run")
    org = await db.organisations.find_one({"id": org_id}, {"_id": 0})
    pdf_bytes = build_payslip(org or {}, run, row)
    return StreamingResponse(
        iter([pdf_bytes]), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip-{employee_id[:8]}-{run["period"]}.pdf"'},
    )
