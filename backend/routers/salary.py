"""Salary components, structures and employee assignments."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.auth import Context, new_id, require_perm
from lib.db import db
from lib.events import emit

router = APIRouter(prefix="/v1/salary", tags=["Salary"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class ComponentIn(BaseModel):
    code: str = Field(min_length=2, max_length=20)
    name: str
    type: str = "earning"  # earning | deduction | employer_contribution
    calc: str = "fixed"  # fixed | pct_gross | pct_basic | gross_balance
    value: float = 0
    taxable: bool = True
    pf_applicable: bool = False
    esi_applicable: bool = True
    ctc_included: bool = True
    effective_from: str | None = None


class StructureIn(BaseModel):
    name: str
    components: list[dict] = []


class AssignmentIn(BaseModel):
    employee_id: str
    structure_id: str
    gross_monthly: float = Field(gt=0)
    effective_from: str


@router.get("/components")
async def list_components(ctx: Context = Depends(require_perm("salary.view"))):
    docs = await db.salary_components.find({"org_id": ctx.org_id}).sort("code", 1).to_list(200)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/components")
async def create_component(input: ComponentIn, ctx: Context = Depends(require_perm("salary.manage"))):
    if await db.salary_components.find_one({"org_id": ctx.org_id, "code": input.code.upper()}):
        raise HTTPException(status_code=409, detail=f"Component code {input.code.upper()} already exists")
    doc = input.model_dump()
    doc["code"] = input.code.upper()
    doc.update({"id": new_id(), "org_id": ctx.org_id, "created_at": now()})
    await db.salary_components.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/components/{component_id}")
async def delete_component(component_id: str, ctx: Context = Depends(require_perm("salary.manage"))):
    await db.salary_components.delete_one({"id": component_id, "org_id": ctx.org_id})
    return {"ok": True}


@router.get("/structures")
async def list_structures(ctx: Context = Depends(require_perm("salary.view"))):
    docs = await db.salary_structures.find({"org_id": ctx.org_id}).sort("created_at", -1).to_list(200)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/structures")
async def create_structure(input: StructureIn, ctx: Context = Depends(require_perm("salary.manage"))):
    doc = {"id": new_id(), "org_id": ctx.org_id, "name": input.name,
           "components": input.components, "created_at": now()}
    await db.salary_structures.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "salary.structure_created", actor=ctx.user, entity="salary_structure",
               entity_id=doc["id"], summary=f"Salary structure '{input.name}' created")
    return doc


@router.put("/structures/{structure_id}")
async def update_structure(structure_id: str, input: StructureIn,
                           ctx: Context = Depends(require_perm("salary.manage"))):
    res = await db.salary_structures.update_one(
        {"id": structure_id, "org_id": ctx.org_id},
        {"$set": {"name": input.name, "components": input.components}},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Structure not found")
    return await db.salary_structures.find_one(
        {"id": structure_id, "org_id": ctx.org_id}, {"_id": 0})


@router.get("/assignments")
async def list_assignments(ctx: Context = Depends(require_perm("salary.view")),
                           employee_id: str | None = None):
    query: dict = {"org_id": ctx.org_id}
    if employee_id:
        query["employee_id"] = employee_id
    docs = await db.salary_assignments.find(query).sort("created_at", -1).to_list(1000)
    for d in docs:
        d.pop("_id", None)
    return docs


@router.post("/assignments")
async def create_assignment(input: AssignmentIn, ctx: Context = Depends(require_perm("salary.manage"))):
    emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    structure = await db.salary_structures.find_one({"id": input.structure_id, "org_id": ctx.org_id})
    if not structure:
        raise HTTPException(status_code=404, detail="Salary structure not found")
    await db.salary_assignments.update_many(
        {"employee_id": input.employee_id, "org_id": ctx.org_id, "active": True},
        {"$set": {"active": False, "superseded_at": now()}},
    )
    doc = {
        "id": new_id(), "org_id": ctx.org_id, "employee_id": input.employee_id,
        "structure_id": input.structure_id, "gross_monthly": input.gross_monthly,
        "effective_from": input.effective_from, "active": True, "created_at": now(),
    }
    await db.salary_assignments.insert_one(doc)
    doc.pop("_id", None)
    await emit(ctx.org_id, "salary.updated", actor=ctx.user, entity="salary_assignment",
               entity_id=doc["id"],
               summary=f"Salary ₹{input.gross_monthly:,.0f}/month assigned to {emp['name']}",
               data={"employee_id": emp["id"], "gross_monthly": input.gross_monthly})
    return doc
