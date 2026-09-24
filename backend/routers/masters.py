"""Masters: departments, locations, designations, cost centres."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lib.auth import Context, new_id, require_perm
from lib.db import db

router = APIRouter(prefix="/v1", tags=["Masters"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class NameIn(BaseModel):
    name: str
    city: str | None = None
    state: str | None = None
    municipality: str | None = None


def _collection(kind: str):
    return {
        "departments": db.departments, "locations": db.locations,
        "designations": db.designations, "cost_centres": db.cost_centres,
    }[kind]


@router.get("/masters/{kind}")
async def list_masters(kind: str, ctx: Context = Depends(require_perm("self.view"))):
    if kind not in ("departments", "locations", "designations", "cost_centres"):
        raise HTTPException(status_code=404, detail="Unknown master type")
    docs = await _collection(kind).find({"org_id": ctx.org_id}).sort("name", 1).to_list(500)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/masters/{kind}")
async def create_master(kind: str, input: NameIn, ctx: Context = Depends(require_perm("settings.manage"))):
    if kind not in ("departments", "locations", "designations", "cost_centres"):
        raise HTTPException(status_code=404, detail="Unknown master type")
    doc = {"id": new_id(), "org_id": ctx.org_id, "name": input.name.strip(),
           "city": input.city or "", "state": input.state or "",
           "municipality": input.municipality or "", "created_at": now()}
    await _collection(kind).insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/masters/{kind}/{item_id}")
async def delete_master(kind: str, item_id: str, ctx: Context = Depends(require_perm("settings.manage"))):
    if kind not in ("departments", "locations", "designations", "cost_centres"):
        raise HTTPException(status_code=404, detail="Unknown master type")
    await _collection(kind).delete_one({"id": item_id, "org_id": ctx.org_id})
    return {"ok": True}
