"""Compliance: versioned statutory rules (with verification flags) and
Full & Final settlement computation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit
from services.ff_engine import compute_settlement
from services.rules import RuleUnavailable, get_rule, rule_ref

router = APIRouter(prefix="/v1/compliance", tags=["Compliance"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class RuleIn(BaseModel):
    jurisdiction: str
    rule_type: str
    state: str | None = None
    params: dict
    effective_from: str
    effective_to: str | None = None
    source: str | None = None
    source_date: str | None = None
    verified: bool = False
    notes: str | None = None


@router.get("/rules")
async def list_rules(ctx: Context = Depends(require_perm("compliance.view")),
                     jurisdiction: str | None = None, rule_type: str | None = None,
                     state: str | None = None, active: bool | None = None):
    # Tenant scoping: platform-wide rules (org_id None) + this tenant's own versions only.
    # Another tenant's rule documents (and their values/notes) are never returned.
    query: dict = {"$or": [{"org_id": None}, {"org_id": {"$exists": False}},
                           {"org_id": ctx.org_id}]}
    if jurisdiction:
        query["jurisdiction"] = jurisdiction
    if rule_type:
        query["rule_type"] = rule_type
    if state:
        query["state"] = state
    if active is not None:
        query["active"] = active
    docs = await db.statutory_rules.find(query).sort([
        ("jurisdiction", 1), ("rule_type", 1), ("state", 1), ("version", -1)]).to_list(500)
    for d in docs:
        d.pop("_id", None)
        d["verification_status"] = "verified" if d.get("verified") else "Requires statutory verification"
        d["scope"] = "organisation" if d.get("org_id") else "platform"
    return docs


@router.post("/rules")
async def add_rule_version(input: RuleIn, ctx: Context = Depends(require_perm("compliance.manage"))):
    """Manually enter a NEW rule version — typically after independently verifying
    the values offline. The system never marks a rule verified on its own.

    The version is owned by the authoring tenant (org_id = ctx.org_id) and is resolved only
    for that tenant, so one customer's rule entry can never alter another's payroll.
    """
    last = await db.statutory_rules.find_one(
        {"jurisdiction": input.jurisdiction, "rule_type": input.rule_type, "state": input.state,
         "$or": [{"org_id": None}, {"org_id": {"$exists": False}}, {"org_id": ctx.org_id}]},
        sort=[("version", -1)])
    doc = input.model_dump()
    doc["id"] = new_id()
    doc["version"] = (last or {}).get("version", 0) + 1
    doc["org_id"] = ctx.org_id
    doc["created_by"] = ctx.user["email"]
    doc["created_at"] = now()
    await db.statutory_rules.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "compliance.rule_added", actor=ctx.user, entity="statutory_rule",
               entity_id=doc["id"],
               summary=f"Statutory rule {input.rule_type} v{doc['version']} added "
                       f"({'verified' if input.verified else 'REQUIRES STATUTORY VERIFICATION'})")
    return doc


class FFIn(BaseModel):
    """Legacy F&F shape. The full workflow (preview → draft → approve → settle →
    statement PDF) lives at /api/v1/settlements; these two endpoints stay for API
    compatibility and delegate to the same engine."""
    employee_id: str
    last_working_day: str
    exit_reason: str | None = None
    notice_pay_days: float = 0  # notice period served short → recovery; extra served → payable
    notice_recovery_days: float = 0
    bonus: float = 0
    incentive: float = 0
    other_earnings: float = 0
    other_deductions: float = 0
    tax_adjustment: float = 0
    notes: str | None = None


@router.get("/ff")
async def list_ff(ctx: Context = Depends(require_perm("ff.view")), employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    docs = await db.ffs.find(query).sort("created_at", -1).to_list(100)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/ff")
async def create_ff(input: FFIn, ctx: Context = Depends(require_perm("ff.manage"))):
    """Compatibility shim: computes and persists a draft settlement through the same
    F&F engine the /api/v1/settlements workflow uses."""
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    org = await db.organisations.find_one({"id": ctx.org_id})
    try:
        body = await compute_settlement(org, emp, input.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    doc = {"id": new_id(), "org_id": ctx.org_id, **body, "status": "draft",
           "inputs": input.model_dump(), "created_by": ctx.user["email"], "created_at": now()}
    await db.ffs.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "ff.created", actor=ctx.user, entity="ff", entity_id=doc["id"],
               summary=f"F&F settlement drafted for {emp['name']}: "
                       f"net {body['net_settlement']:,.2f}",
               data={"settlement_id": doc["id"], "employee_id": emp["id"],
                     "net_settlement": body["net_settlement"]})
    return doc
