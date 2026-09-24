"""Leave types, policies, balances and the request→approval flow.

Approving an unpaid leave writes unpaid_leave attendance rows, which the payroll
engine turns into LOP — leave always feeds payroll deterministically."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from lib.team_scope import manager_team_ids, require_manager_team_member

router = APIRouter(prefix="/v1/leave", tags=["Leave"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class LeaveTypeIn(BaseModel):
    code: str = Field(min_length=2, max_length=10)
    name: str
    annual_quota: float = Field(ge=0)
    paid: bool = True
    carry_forward: bool = True


class LeaveRequestIn(BaseModel):
    employee_id: str | None = None
    leave_type_id: str
    from_date: str
    to_date: str
    days: float = Field(gt=0)
    reason: str | None = None


@router.get("/types")
async def list_types(ctx: Context = Depends(require_perm("leave.view"))):
    docs = await db.leave_types.find({"org_id": ctx.org_id}).sort("code", 1).to_list(50)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/types")
async def create_type(input: LeaveTypeIn, ctx: Context = Depends(require_perm("leave.manage"))):
    if await db.leave_types.find_one({"org_id": ctx.org_id, "code": input.code.upper()}):
        raise HTTPException(status_code=409, detail=f"Leave type {input.code.upper()} already exists")
    doc = input.model_dump()
    doc["code"] = input.code.upper()
    doc.update({"id": new_id(), "org_id": ctx.org_id, "accrual": "monthly", "created_at": now()})
    await db.leave_types.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/balances")
async def balances(ctx: Context = Depends(require_perm("leave.view")), employee_id: str | None = None):
    if ctx.role == "EMPLOYEE":
        employee_id = ctx.user.get("employee_id")
        if not employee_id:
            return []
    elif not employee_id:
        raise HTTPException(status_code=422, detail="employee_id is required")
    elif ctx.role == "MANAGER":
        await require_manager_team_member(ctx, employee_id)
    docs = await db.leave_balances.find({"org_id": ctx.org_id, "employee_id": employee_id}).to_list(50)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.get("/requests")
async def list_requests(ctx: Context = Depends(require_perm("leave.view")),
                        status: str | None = None, employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if ctx.role == "EMPLOYEE":
        query["employee_id"] = ctx.user.get("employee_id") or "__none__"
    elif ctx.role == "MANAGER":
        team_ids = await manager_team_ids(ctx)
        query["employee_id"] = employee_id if employee_id in team_ids else {"$in": team_ids}
        if employee_id and employee_id not in team_ids:
            query["employee_id"] = {"$in": []}
    elif employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    docs = await db.leave_requests.find(query).sort("created_at", -1).to_list(500)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/requests")
async def create_request(input: LeaveRequestIn, ctx: Context = Depends(require_perm("leave.view"))):
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
    if ctx.role == "MANAGER":
        await require_manager_team_member(ctx, employee_id)
    lt = await db.leave_types.find_one({"id": input.leave_type_id, "org_id": ctx.org_id})
    if not lt:
        raise HTTPException(status_code=404, detail="Leave type not found")
    if input.from_date > input.to_date:
        raise HTTPException(status_code=422, detail="from_date must be on or before to_date")
    doc = {
        "id": new_id(), "org_id": ctx.org_id, "employee_id": employee_id,
        "employee_name": emp["name"], "leave_type_id": lt["id"], "leave_code": lt["code"],
        "leave_name": lt["name"], "paid": lt["paid"], "unpaid": not lt["paid"],
        "from_date": input.from_date, "to_date": input.to_date, "days": input.days,
        "reason": input.reason, "status": "pending", "created_at": now(),
        "decided_by": None, "decided_at": None,
    }
    await db.leave_requests.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _decide(ctx: Context, request_id: str, approve: bool) -> dict:
    req = await db.leave_requests.find_one({"id": request_id, "org_id": ctx.org_id})
    if not req:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req['status']}")
    if ctx.role == "MANAGER":
        emp = await db.employees.find_one({"id": req["employee_id"], "org_id": ctx.org_id})
        me_emp = await db.employees.find_one({"org_id": ctx.org_id, "user_id": ctx.user_id})
        if not emp or not me_emp or emp.get("reporting_manager_id") != me_emp["id"]:
            raise HTTPException(status_code=403, detail="You can only approve leave for your own team")

    if approve:
        # Attendance rows per day — this is how leave feeds payroll LOP
        from datetime import date, timedelta
        start = date.fromisoformat(req["from_date"])
        end = date.fromisoformat(req["to_date"])
        att_status = "paid_leave" if req["paid"] else "unpaid_leave"
        day = start
        while day <= end:
            dstr = day.isoformat()
            existing = await db.attendance.find_one(
                {"org_id": ctx.org_id, "employee_id": req["employee_id"], "date": dstr})
            if existing:
                await db.attendance.update_one(
                    {"id": existing["id"]},
                    {"$set": {"status": att_status, "days": 1, "overtime_hours": 0,
                              "period": dstr[:7], "leave_request_id": request_id}})
            else:
                await db.attendance.insert_one({
                    "id": new_id(), "org_id": ctx.org_id, "employee_id": req["employee_id"],
                    "date": dstr, "status": att_status, "days": 1, "overtime_hours": 0,
                    "period": dstr[:7], "leave_request_id": request_id,
                })
            day += timedelta(days=1)
        balance = await db.leave_balances.find_one(
            {"org_id": ctx.org_id, "employee_id": req["employee_id"],
             "leave_type_id": req["leave_type_id"]})
        if balance:
            await db.leave_balances.update_one(
                {"id": balance["id"]}, {"$inc": {"used": req["days"]}})
        else:
            await db.leave_balances.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "employee_id": req["employee_id"],
                "leave_type_id": req["leave_type_id"], "leave_code": req["leave_code"],
                "granted": 0, "used": req["days"], "year": req["from_date"][:4],
            })

    await db.leave_requests.update_one({"id": request_id, "org_id": ctx.org_id}, {
        "$set": {"status": "approved" if approve else "rejected",
                 "decided_by": ctx.user["email"], "decided_at": now()},
    })
    # Notify the requesting employee on every registered channel (in-app now; email /
    # PWA push / mobile push queue until a provider is configured).
    applicant = await db.users.find_one({"employee_id": req["employee_id"],
                                         "memberships.org_id": ctx.org_id})
    await emit(ctx.org_id, "leave.approved" if approve else "leave.rejected", actor=ctx.user,
               entity="leave_request", entity_id=request_id,
               summary=f"Leave {req['leave_code']} ({req['from_date']}→{req['to_date']}) "
                       f"{'approved' if approve else 'rejected'} for {req['employee_name']}",
               notify_user_ids=[applicant["id"]] if applicant else None,
               data={"employee_id": req["employee_id"], "days": req["days"],
                     "leave_code": req["leave_code"], "from_date": req["from_date"],
                     "to_date": req["to_date"]})
    return {"ok": True}


@router.post("/requests/{request_id}/approve")
async def approve(request_id: str, ctx: Context = Depends(require_perm("leave.approve"))):
    return await _decide(ctx, request_id, True)


@router.post("/requests/{request_id}/reject")
async def reject(request_id: str, ctx: Context = Depends(require_perm("leave.approve"))):
    return await _decide(ctx, request_id, False)
