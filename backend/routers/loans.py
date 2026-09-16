"""Loans and salary advances with deterministic amortisation schedules."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1/loans", tags=["Loans"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def build_schedule(principal: float, annual_rate_pct: float, tenure: int, start_period: str) -> tuple[float, list[dict]]:
    r = annual_rate_pct / 1200.0
    if r == 0:
        emi = round(principal / tenure, 2)
    else:
        emi = round(principal * r / (1 - (1 + r) ** -tenure), 2)
    balance = principal
    year, month = int(start_period[:4]), int(start_period[5:7])
    schedule = []
    for n in range(1, tenure + 1):
        interest = round(balance * r, 2)
        principal_part = round(min(emi - interest, balance), 2)
        balance = round(balance - principal_part, 2)
        if n == tenure:
            principal_part = round(principal_part + balance, 2)
            balance = 0.0
        schedule.append({
            "n": n, "period": f"{year:04d}-{month:02d}", "emi": round(principal_part + interest, 2),
            "principal": principal_part, "interest": interest, "balance": balance,
        })
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return emi, schedule


class LoanIn(BaseModel):
    employee_id: str
    name: str = "Salary advance"
    principal: float = Field(gt=0)
    interest_rate: float = Field(default=0, ge=0, le=60)
    tenure_months: int = Field(ge=1, le=120)
    start_period: str  # YYYY-MM — first deduction month
    deduct_from_payroll: bool = True


@router.get("")
async def list_loans(ctx: Context = Depends(require_perm("loans.view")),
                     status: str | None = None, employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if ctx.role == "EMPLOYEE":
        query["employee_id"] = ctx.user.get("employee_id") or "__none__"
    elif employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    docs = await db.loans.find(query).sort("created_at", -1).to_list(200)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("")
async def create_loan(input: LoanIn, ctx: Context = Depends(require_perm("loans.manage"))):
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    emi, schedule = build_schedule(input.principal, input.interest_rate, input.tenure_months, input.start_period)
    doc = {
        "id": new_id(), "org_id": ctx.org_id, "employee_id": input.employee_id,
        "employee_name": emp["name"], "name": input.name, "principal": input.principal,
        "interest_rate": input.interest_rate, "tenure_months": input.tenure_months,
        "start_period": input.start_period, "emi": emi, "schedule": schedule,
        "outstanding": input.principal, "status": "active",
        "deduct_from_payroll": input.deduct_from_payroll, "created_at": now(),
    }
    await db.loans.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "loan.created", actor=ctx.user, entity="loan", entity_id=doc["id"],
               summary=f"Loan '{input.name}' of ₹{input.principal:,.0f} for {emp['name']} "
                       f"(EMI ₹{emi:,.0f} × {input.tenure_months})")
    return doc


@router.get("/{loan_id}")
async def get_loan(loan_id: str, ctx: Context = Depends(require_perm("loans.view"))):
    doc = await db.loans.find_one({"id": loan_id, "org_id": ctx.org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Loan not found")
    repayments = await db.loan_repayments.find({"loan_id": loan_id, "org_id": ctx.org_id},
                                               {"_id": 0}).to_list(200)
    doc["repayments"] = repayments
    return doc


class CloseIn(BaseModel):
    note: str | None = None


@router.post("/{loan_id}/close")
async def close_loan(loan_id: str, input: CloseIn, ctx: Context = Depends(require_perm("loans.manage"))):
    doc = await db.loans.find_one({"id": loan_id, "org_id": ctx.org_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Loan not found")
    if doc["status"] != "active":
        raise HTTPException(status_code=409, detail=f"Loan already {doc['status']}")
    await db.loans.update_one({"id": loan_id}, {
        "$set": {"status": "closed", "closed_at": now(), "close_note": input.note},
    })
    await emit(ctx.org_id, "loan.closed", actor=ctx.user, entity="loan", entity_id=loan_id,
               summary=f"Loan '{doc['name']}' closed with outstanding ₹{doc['outstanding']:,.0f}")
    return {"ok": True}
