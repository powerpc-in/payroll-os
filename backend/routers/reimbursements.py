"""Reimbursements — claims with taxability, approval and payroll integration."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1/reimbursements", tags=["Reimbursements"])


def now() -> datetime:
    return datetime.now(timezone.utc)


CATEGORIES = ["travel", "fuel", "telephone", "internet", "food", "medical", "books", "relocation", "other"]


class ReimbIn(BaseModel):
    employee_id: str | None = None
    category: str
    amount: float = Field(gt=0)
    description: str | None = None
    date: str
    taxable: bool = False


@router.get("")
async def list_reimbursements(ctx: Context = Depends(require_perm("reimbursements.view")),
                              status: str | None = None, employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if ctx.role == "EMPLOYEE":
        query["employee_id"] = ctx.user.get("employee_id") or "__none__"
    elif employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    docs = await db.reimbursements.find(query).sort("created_at", -1).to_list(500)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("")
async def create_reimbursement(input: ReimbIn, ctx: Context = Depends(require_perm("reimbursements.view"))):
    if ctx.role == "EMPLOYEE":
        employee_id = ctx.user.get("employee_id") or ""
        if not employee_id:
            raise HTTPException(status_code=400, detail="Your login is not linked to an employee record")
    else:
        employee_id = input.employee_id or ctx.user.get("employee_id") or ""
        if not employee_id:
            raise HTTPException(status_code=422, detail="employee_id is required")
    emp = await db.employees.find_one({"id": employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    if input.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of {CATEGORIES}")
    doc = {
        "id": new_id(), "org_id": ctx.org_id, "employee_id": employee_id,
        "employee_name": emp["name"], "category": input.category, "amount": input.amount,
        "description": input.description, "date": input.date, "taxable": input.taxable,
        "status": "pending", "approved_amount": 0, "decided_by": None, "paid_run_id": None,
        "created_at": now(),
    }
    await db.reimbursements.insert_one(doc)
    doc.pop("_id", None)
    return doc


class ApproveIn(BaseModel):
    approved_amount: float = Field(ge=0)


@router.post("/{reimbursement_id}/approve")
async def approve(reimbursement_id: str, input: ApproveIn,
                  ctx: Context = Depends(require_perm("reimbursements.approve"))):
    doc = await db.reimbursements.find_one({"id": reimbursement_id, "org_id": ctx.org_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Reimbursement not found")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Claim already {doc['status']}")
    if input.approved_amount > doc["amount"]:
        raise HTTPException(status_code=422, detail="Approved amount cannot exceed claimed amount")
    await db.reimbursements.update_one({"id": reimbursement_id}, {
        "$set": {"status": "approved", "approved_amount": input.approved_amount,
                 "decided_by": ctx.user["email"], "decided_at": now()},
    })
    await emit(ctx.org_id, "reimbursement.approved", actor=ctx.user, entity="reimbursement",
               entity_id=reimbursement_id,
               summary=f"Reimbursement of ₹{input.approved_amount:,.0f} approved for {doc['employee_name']}",
               data={"employee_id": doc["employee_id"], "approved_amount": input.approved_amount})
    return {"ok": True}


class RejectIn(BaseModel):
    reason: str | None = None


@router.post("/{reimbursement_id}/reject")
async def reject(reimbursement_id: str, input: RejectIn,
                 ctx: Context = Depends(require_perm("reimbursements.approve"))):
    doc = await db.reimbursements.find_one({"id": reimbursement_id, "org_id": ctx.org_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Reimbursement not found")
    if doc["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Claim already {doc['status']}")
    await db.reimbursements.update_one({"id": reimbursement_id}, {
        "$set": {"status": "rejected", "decided_by": ctx.user["email"], "decided_at": now(),
                 "reject_reason": input.reason},
    })
    await emit(ctx.org_id, "reimbursement.rejected", actor=ctx.user, entity="reimbursement",
               entity_id=reimbursement_id,
               summary=f"Reimbursement rejected for {doc['employee_name']}")
    return {"ok": True}
