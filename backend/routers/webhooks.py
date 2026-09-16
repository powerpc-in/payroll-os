"""Outbound webhooks: endpoints, event subscriptions, signed delivery, retries,
failure handling and a full delivery log (per endpoint and org-wide).

Deliveries are real HTTP calls to the configured URL — the recorded result always
reflects the endpoint's actual response. Nothing is ever marked delivered optimistically.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import (EVENT_CATALOG, MAX_ATTEMPTS, SIGNATURE_VERSION, WEBHOOK_EVENTS,
                        deliver, emit)

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class WebhookIn(BaseModel):
    name: str
    url: str
    secret: str = Field(min_length=8)
    events: list[str]
    active: bool = True

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


@router.get("/events")
async def events(ctx: Context = Depends(require_perm("webhooks.manage"))):
    """The platform event catalog — the same list connectors subscribe to."""
    return [e for e in EVENT_CATALOG if e["webhook"]]


@router.get("/signature-scheme")
async def signature_scheme(ctx: Context = Depends(require_perm("webhooks.manage"))):
    return {
        "header": "X-Webhook-Signature",
        "format": f"{SIGNATURE_VERSION}=hex(hmac_sha256(secret, timestamp + '.' + raw_body))",
        "timestamp_header": "X-Webhook-Timestamp",
        "delivery_header": "X-Webhook-Delivery",
        "event_header": "X-Webhook-Event",
        "max_attempts": MAX_ATTEMPTS,
        "note": "Reject a request whose timestamp is older than your tolerance window, "
                "then recompute the HMAC over the raw body to verify authenticity.",
    }


@router.get("")
async def list_webhooks(ctx: Context = Depends(require_perm("webhooks.manage"))):
    docs = await db.webhooks.find({"org_id": ctx.org_id}, {"_id": 0}) \
        .sort("created_at", -1).to_list(100)
    for d in docs:
        d["failed_deliveries"] = await db.webhook_deliveries.count_documents(
            {"org_id": ctx.org_id, "webhook_id": d["id"], "status": "failed"})
    return docs


@router.post("")
async def create_webhook(input: WebhookIn, ctx: Context = Depends(require_perm("webhooks.manage"))):
    bad = [e for e in input.events if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown events: {bad}")
    doc = input.model_dump()
    doc.update({"id": new_id(), "org_id": ctx.org_id, "created_at": now()})
    await db.webhooks.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "webhook.created", actor=ctx.user, entity="webhook",
               entity_id=doc["id"], summary=f"Webhook '{input.name}' registered for "
                                            f"{len(input.events)} event(s)")
    return doc


@router.put("/{webhook_id}")
async def update_webhook(webhook_id: str, input: WebhookIn,
                         ctx: Context = Depends(require_perm("webhooks.manage"))):
    bad = [e for e in input.events if e not in WEBHOOK_EVENTS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown events: {bad}")
    res = await db.webhooks.update_one({"id": webhook_id, "org_id": ctx.org_id},
                                       {"$set": input.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await emit(ctx.org_id, "webhook.updated", actor=ctx.user, entity="webhook",
               entity_id=webhook_id, summary=f"Webhook '{input.name}' updated")
    return await db.webhooks.find_one({"id": webhook_id, "org_id": ctx.org_id}, {"_id": 0})


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    await db.webhooks.delete_one({"id": webhook_id, "org_id": ctx.org_id})
    await db.webhook_deliveries.delete_many({"webhook_id": webhook_id, "org_id": ctx.org_id})
    return {"ok": True}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    """Sends a real signed `webhook.test` ping and returns the recorded delivery —
    the result is whatever the endpoint actually answered."""
    hook = await db.webhooks.find_one({"id": webhook_id, "org_id": ctx.org_id})
    if not hook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    payload = {"event": "webhook.test", "org_id": ctx.org_id, "entity": "webhook",
               "entity_id": webhook_id, "timestamp": now().isoformat(),
               "data": {"test": True, "triggered_by": ctx.user["email"]}}
    delivery_id = new_id()
    await db.webhook_deliveries.insert_one({
        "id": delivery_id, "org_id": ctx.org_id, "webhook_id": webhook_id,
        "event": "webhook.test", "url": hook["url"], "payload": payload,
        "status": "pending", "success": False, "status_code": None, "attempts": 0,
        "attempt_log": [], "error": None, "next_retry_at": None, "created_at": now()})
    delivery = await deliver(delivery_id)
    return {"ok": bool(delivery.get("success")), "delivery": delivery}


@router.get("/deliveries")
async def all_deliveries(ctx: Context = Depends(require_perm("webhooks.manage")),
                         status: str | None = None, event: str | None = None, limit: int = 100):
    query: dict = {"org_id": ctx.org_id}
    if status:
        query["status"] = status
    if event:
        query["event"] = event
    docs = await db.webhook_deliveries.find(query, {"_id": 0, "payload": 0}) \
        .sort("created_at", -1).to_list(min(limit, 500))
    return {
        "items": docs,
        "counts": {
            "success": await db.webhook_deliveries.count_documents({"org_id": ctx.org_id, "status": "success"}),
            "failed": await db.webhook_deliveries.count_documents({"org_id": ctx.org_id, "status": "failed"}),
            "pending": await db.webhook_deliveries.count_documents({"org_id": ctx.org_id, "status": "pending"}),
        },
    }


@router.get("/deliveries/{delivery_id}")
async def delivery_detail(delivery_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    doc = await db.webhook_deliveries.find_one({"id": delivery_id, "org_id": ctx.org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return doc


@router.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    """Re-sends the original stored payload. Attempt history is appended, never reset."""
    doc = await db.webhook_deliveries.find_one({"id": delivery_id, "org_id": ctx.org_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if doc.get("status") == "success":
        raise HTTPException(status_code=409, detail="This delivery already succeeded")
    delivery = await deliver(delivery_id)
    return {"ok": bool(delivery.get("success")), "delivery": delivery}


@router.get("/{webhook_id}/deliveries")
async def deliveries(webhook_id: str, ctx: Context = Depends(require_perm("webhooks.manage"))):
    docs = await db.webhook_deliveries.find(
        {"org_id": ctx.org_id, "webhook_id": webhook_id}, {"_id": 0, "payload": 0}) \
        .sort("created_at", -1).to_list(50)
    return docs
