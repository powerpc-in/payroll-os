"""Full & Final settlement workflow: compute → review → approve → settle (exit processing).

Settling a settlement is the authoritative exit event: it closes recovered loans, marks
settled reimbursements paid, flips the employee to `exited` with the exit date/reason, and
emits `employee.terminated` + `ff.settled` on the shared event bus (audit + notifications +
outbound webhooks + any future connector).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from services.ff_engine import compute_settlement
from services.ff_statement import build_ff_statement

router = APIRouter(prefix="/v1/settlements", tags=["Full & Final"])

STATUSES = ["draft", "approved", "settled"]


def now() -> datetime:
    return datetime.now(timezone.utc)


class SettlementIn(BaseModel):
    employee_id: str
    last_working_day: str
    exit_reason: str | None = None
    notice_pay_days: float = 0
    notice_recovery_days: float = 0
    encash_days_override: float | None = None
    bonus: float = 0
    incentive: float = 0
    other_earnings: float = 0
    other_deductions: float = 0
    tax_adjustment: float = 0
    notes: str | None = None


async def _load(ff_id: str, ctx: Context) -> dict:
    doc = await db.ffs.find_one({"id": ff_id, "org_id": ctx.org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Settlement not found")
    return doc


@router.get("")
async def list_settlements(ctx: Context = Depends(require_perm("ff.view")),
                           employee_id: str | None = None, status: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    docs = await db.ffs.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs


@router.get("/preview")
async def preview(employee_id: str, last_working_day: str,
                  notice_pay_days: float = 0, notice_recovery_days: float = 0,
                  bonus: float = 0, incentive: float = 0, other_earnings: float = 0,
                  other_deductions: float = 0, tax_adjustment: float = 0,
                  ctx: Context = Depends(require_perm("ff.manage"))):
    """Computes a settlement WITHOUT persisting it, so an admin can review the numbers
    (and any fail-safe notes) before creating the record."""
    body = await _compute(ctx, SettlementIn(
        employee_id=employee_id, last_working_day=last_working_day,
        notice_pay_days=notice_pay_days, notice_recovery_days=notice_recovery_days,
        bonus=bonus, incentive=incentive, other_earnings=other_earnings,
        other_deductions=other_deductions, tax_adjustment=tax_adjustment))
    body["status"] = "preview"
    body["id"] = ""
    return body


async def _compute(ctx: Context, input: SettlementIn) -> dict:
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    org = await db.organisations.find_one({"id": ctx.org_id})
    try:
        return await compute_settlement(org, emp, input.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def create_settlement(input: SettlementIn,
                            ctx: Context = Depends(require_perm("ff.manage"))):
    existing = await db.ffs.find_one({"org_id": ctx.org_id, "employee_id": input.employee_id,
                                      "status": {"$ne": "settled"}})
    if existing:
        raise HTTPException(status_code=409,
                            detail=f"An open settlement ({existing['status']}) already exists "
                                   f"for this employee — settle or delete it first")
    body = await _compute(ctx, input)
    doc = {"id": new_id(), "org_id": ctx.org_id, **body, "status": "draft",
           "inputs": input.model_dump(), "created_by": ctx.user["email"], "created_at": now()}
    await db.ffs.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "ff.created", actor=ctx.user, entity="ff", entity_id=doc["id"],
               summary=f"F&F settlement drafted for {body['employee_name']} "
                       f"(LWD {body['last_working_day']}): net {body['net_settlement']:,.2f}",
               data={"settlement_id": doc["id"], "employee_id": input.employee_id,
                     "net_settlement": body["net_settlement"],
                     "last_working_day": body["last_working_day"]})
    return doc


@router.post("/{ff_id}/recompute")
async def recompute(ff_id: str, input: SettlementIn,
                    ctx: Context = Depends(require_perm("ff.manage"))):
    doc = await _load(ff_id, ctx)
    if doc["status"] == "settled":
        raise HTTPException(status_code=409, detail="A settled settlement is immutable")
    body = await _compute(ctx, input)
    await db.ffs.update_one({"id": ff_id, "org_id": ctx.org_id},
                            {"$set": {**body, "inputs": input.model_dump(),
                                      "status": "draft", "updated_at": now()}})
    updated = await _load(ff_id, ctx)
    await emit(ctx.org_id, "ff.recomputed", actor=ctx.user, entity="ff", entity_id=ff_id,
               old={"net_settlement": doc.get("net_settlement")},
               new={"net_settlement": updated.get("net_settlement")},
               summary=f"F&F settlement recomputed for {updated['employee_name']}")
    return updated


@router.post("/{ff_id}/approve")
async def approve(ff_id: str, ctx: Context = Depends(require_perm("payroll.approve"))):
    doc = await _load(ff_id, ctx)
    if doc["status"] != "draft":
        raise HTTPException(status_code=409,
                            detail=f"Settlement is '{doc['status']}' — approval requires 'draft'")
    await db.ffs.update_one({"id": ff_id, "org_id": ctx.org_id},
                            {"$set": {"status": "approved", "approved_by": ctx.user["email"],
                                      "approved_at": now()}})
    updated = await _load(ff_id, ctx)
    await emit(ctx.org_id, "ff.approved", actor=ctx.user, entity="ff", entity_id=ff_id,
               old={"status": "draft"}, new={"status": "approved"},
               summary=f"F&F settlement approved for {doc['employee_name']} "
                       f"(net {doc['net_settlement']:,.2f})",
               data={"settlement_id": ff_id, "employee_id": doc["employee_id"],
                     "net_settlement": doc["net_settlement"]})
    return updated


class SettleIn(BaseModel):
    payment_reference: str | None = None


@router.post("/{ff_id}/settle")
async def settle(ff_id: str, input: SettleIn,
                 ctx: Context = Depends(require_perm("payroll.lock"))):
    """Exit processing. Irreversible: the settlement becomes immutable, recovered loans
    close, settled reimbursements are marked paid and the employee record exits."""
    doc = await _load(ff_id, ctx)
    if doc["status"] != "approved":
        raise HTTPException(status_code=409,
                            detail=f"Settlement is '{doc['status']}' — settling requires 'approved'")

    for rid in doc.get("reimbursement_ids", []):
        await db.reimbursements.update_one(
            {"id": rid, "org_id": ctx.org_id, "status": "approved"},
            {"$set": {"status": "paid", "paid_via_settlement_id": ff_id}})
    recovered = {r["code"] for r in doc.get("recoveries", [])}
    if "LOAN_REC" in recovered:
        for lid in doc.get("loan_ids", []):
            loan = await db.loans.find_one({"id": lid, "org_id": ctx.org_id})
            if not loan:
                continue
            await db.loan_repayments.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "loan_id": lid,
                "employee_id": doc["employee_id"], "period": doc["period"],
                "emi": loan.get("outstanding", 0), "principal": loan.get("outstanding", 0),
                "interest": 0, "paid_via": f"settlement:{ff_id}", "created_at": now()})
            await db.loans.update_one({"id": lid, "org_id": ctx.org_id}, {"$set": {
                "outstanding": 0, "status": "closed", "closed_at": now(),
                "closed_via_settlement_id": ff_id}})

    emp = await db.employees.find_one({"id": doc["employee_id"], "org_id": ctx.org_id})
    old_status = (emp or {}).get("status")
    await db.employees.update_one(
        {"id": doc["employee_id"], "org_id": ctx.org_id},
        {"$set": {"status": "exited", "exit_date": doc["last_working_day"],
                  "exit_reason": doc.get("exit_reason"), "settlement_id": ff_id}})
    await db.salary_assignments.update_many(
        {"org_id": ctx.org_id, "employee_id": doc["employee_id"], "active": True},
        {"$set": {"active": False, "ended_on": doc["last_working_day"]}})

    await db.ffs.update_one({"id": ff_id, "org_id": ctx.org_id}, {"$set": {
        "status": "settled", "settled_by": ctx.user["email"], "settled_at": now(),
        "payment_reference": input.payment_reference}})
    updated = await _load(ff_id, ctx)

    user = await db.users.find_one({"employee_id": doc["employee_id"],
                                    "memberships.org_id": ctx.org_id})
    await emit(ctx.org_id, "ff.settled", actor=ctx.user, entity="ff", entity_id=ff_id,
               old={"status": "approved"}, new={"status": "settled"},
               summary=f"F&F settled for {doc['employee_name']}: net {doc['net_settlement']:,.2f}",
               notify_user_ids=[user["id"]] if user else None,
               data={"settlement_id": ff_id, "employee_id": doc["employee_id"],
                     "net_settlement": doc["net_settlement"],
                     "payment_reference": input.payment_reference})
    await emit(ctx.org_id, "employee.terminated", actor=ctx.user, entity="employee",
               entity_id=doc["employee_id"], old={"status": old_status},
               new={"status": "exited", "exit_date": doc["last_working_day"]},
               summary=f"{doc['employee_name']} exited on {doc['last_working_day']}",
               data={"employee_id": doc["employee_id"], "employee_code": doc.get("employee_code"),
                     "exit_date": doc["last_working_day"],
                     "exit_reason": doc.get("exit_reason"), "settlement_id": ff_id})
    return updated


@router.delete("/{ff_id}")
async def delete_settlement(ff_id: str, ctx: Context = Depends(require_perm("ff.manage"))):
    doc = await _load(ff_id, ctx)
    if doc["status"] == "settled":
        raise HTTPException(status_code=409, detail="A settled settlement is immutable")
    await db.ffs.delete_one({"id": ff_id, "org_id": ctx.org_id})
    await emit(ctx.org_id, "ff.deleted", actor=ctx.user, entity="ff", entity_id=ff_id,
               summary=f"Draft F&F settlement deleted for {doc['employee_name']}")
    return {"ok": True}


@router.get("/{ff_id}/statement")
async def statement(ff_id: str, ctx: Context = Depends(require_perm("ff.view"))):
    doc = await _load(ff_id, ctx)
    org = await db.organisations.find_one({"id": ctx.org_id})
    pdf = build_ff_statement(org or {}, doc)
    await emit(ctx.org_id, "ff.statement_generated", actor=ctx.user, entity="ff", entity_id=ff_id,
               summary=f"F&F statement downloaded for {doc['employee_name']}",
               data={"settlement_id": ff_id, "employee_id": doc["employee_id"]})
    name = f"FF-{(doc.get('employee_code') or doc['employee_id'][:6])}-{doc['last_working_day']}.pdf"
    return StreamingResponse(iter([pdf]), media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
