"""Audit trail — every recorded action, queryable."""

from fastapi import APIRouter, Depends, Query

from lib.auth import Context, require_perm
from lib.db import db

router = APIRouter(prefix="/v1", tags=["Audit"])


@router.get("/audit")
async def list_audit(ctx: Context = Depends(require_perm("audit.view")),
                     page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
                     entity: str | None = None, q: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if entity:
        query["entity"] = entity
    if q:
        query["$or"] = [{"summary": {"$regex": q, "$options": "i"}},
                        {"action": {"$regex": q, "$options": "i"}}]
    total = await db.audit_logs.count_documents(query)
    docs = await db.audit_logs.find(query, {"_id": 0}).sort("created_at", -1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit)
    return {"items": docs, "total": total, "page": page, "limit": limit}
