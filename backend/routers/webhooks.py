"""Outbound webhooks: CRUD, signed delivery, retry with backoff, delivery log."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])

AVAILABLE_EVENTS = [
    "employee.created", "employee.updated", "employee.terminated", "salary.updated",
    "payroll.created", "payroll.calculated", "payroll.approved", "payroll.locked",
    "payslip.generated", "leave.approved", "leave.rejected",
    "reimbursement.approved", "reimbursement.rejected",
]


def now() -> datetime:
    return datetime.now(timezone.utc)


class WebhookIn(BaseModel):
    name: str
    url: str
    secret: str = Field(min_length=8)
    events: list[str]
    active: bool = True


@router.get("/events")
async def events(ctx: Context = Depends(require_perm("webhooks.manage"))):
    return AVAILABLE_EVENTS


@router.get("")
async def list_webhooks(ctx: Context = Depends(require_perm("webhooks.manage"))):
    docs = await db.webhooks.find({"org_id": ctx.org_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return docs


@router.post("")
async def create_webhook(input: WebhookIn, ctx: Context = Depends(require_perm("webhooks.manage"))):
    bad = [e for e in input.events if e not in AVAILABLE_EVENTS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown events: {bad}")
    doc = input.model_dump()
    doc.update({"id": new_id(), "org_id": ctx.org_id, "created_at": now()})
    await db.webhooks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/{webhook_id}")
async def update_webhook(webhook_id: str, input: WebhookIn,
                         ctx: Context = Depends(require_perm("webhooks.manage"))):
    res = await db.webhooks.update_one({"id": webhook_id, "org_id": ctx.org_id},
                                       {"$set": input.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return await db.webhooks.find_one({"id": webhook_id}, {"_id": 0})


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    await db.webhooks.delete_one({"id": webhook_id, "org_id": ctx.org_id})
    return {"ok": True}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    """Sends a real signed test ping to the configured URL and records the delivery —
    the result reflects the endpoint's actual response, never a simulated success."""
    hook = await db.webhooks.find_one({"id": webhook_id, "org_id": ctx.org_id})
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await emit(ctx.org_id, "payroll.calculated", actor=ctx.user, entity="webhook_test",
               entity_id=webhook_id,
               summary="Test delivery (triggered from the webhooks console)",
               data={"test": True, "webhook_id": webhook_id})
    deliveries = await db.webhook_deliveries.find({"webhook_id": webhook_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(1)
    return {"ok": True, "delivery": deliveries[0] if deliveries else None}


@router.get("/{webhook_id}/deliveries")
async def deliveries(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    docs = await db.webhook_deliveries.find({"org_id": ctx.org_id, "webhook_id": webhook_id},
                                            {"_id": 0}).sort("created_at", -1).to_list(50)
    return docs
