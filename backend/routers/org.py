"""Organisation, onboarding wizard, org users/roles, jurisdiction registry exposure."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from lib.auth import Context, hash_password, new_id, require_perm
from lib.db import db
from lib.events import emit
from jurisdictions.registry import list_jurisdictions
from lib.dates import today_iso
from lib.rbac import ROLES, permissions_for_role
from services import payroll_service
from services.statutory_profile_models import StatutoryEstablishmentIn
from services.tax_year_profiles import TaxYearProfileIn, upsert_tax_profile

router = APIRouter(prefix="/v1", tags=["Organisation"])


def now() -> datetime:
    return datetime.now(timezone.utc)


class OrgUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    jurisdiction: str | None = None
    pay_frequency: str | None = None
    pay_day: str | None = None
    accept_unverified_statutory_values: bool | None = None


class EmployeeSeed(BaseModel):
    name: str
    email: EmailStr | None = None
    phone: str | None = None
    department: str | None = None
    designation: str | None = None
    gross_monthly: float
    joining_date: str
    state: str | None = None
    tax_regime: str = "new"
    pf_applicable: bool = True
    esi_applicable: bool = True
    tax_year_profile: TaxYearProfileIn | None = None


class OnboardingIn(BaseModel):
    company: dict = {}
    payroll: dict = {}
    statutory: dict = {}
    structure_name: str = "Standard India Structure"
    basic_pct: float = 40
    hra_pct: float = 50
    locations: list[dict] = []
    statutory_establishments: list[StatutoryEstablishmentIn] = []
    leave_types: list[dict] = []
    employees: list[EmployeeSeed] = []
    run_test_payroll: bool = False


@router.get("/org")
async def get_org(ctx: Context = Depends(require_perm("self.view"))):
    org = await db.organisations.find_one({"id": ctx.org_id}, {"_id": 0})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return org


@router.put("/org")
async def update_org(input: OrgUpdate, ctx: Context = Depends(require_perm("settings.manage"))):
    org = await db.organisations.find_one({"id": ctx.org_id})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    old = dict(org)
    sets: dict = {}
    for field in ("name", "address", "city", "state", "jurisdiction"):
        val = getattr(input, field)
        if val is not None:
            sets[field] = val
    settings = dict(org.get("payroll_settings") or {})
    if input.pay_frequency is not None:
        settings["pay_frequency"] = input.pay_frequency
    if input.pay_day is not None:
        settings["pay_day"] = input.pay_day
    if input.accept_unverified_statutory_values is not None:
        settings["accept_unverified_statutory_values"] = input.accept_unverified_statutory_values
    sets["payroll_settings"] = settings
    await db.organisations.update_one({"id": ctx.org_id}, {"$set": sets})
    await emit(ctx.org_id, "organisation.updated", actor=ctx.user, entity="organisation",
               entity_id=ctx.org_id, old={k: old.get(k) for k in sets},
               new=sets, summary="Organisation settings updated")
    return await db.organisations.find_one({"id": ctx.org_id}, {"_id": 0})


@router.post("/org/onboarding")
async def onboarding(input: OnboardingIn, ctx: Context = Depends(require_perm("settings.manage"))):
    if any(seed.tax_year_profile for seed in input.employees) and not ctx.can("tax.manage"):
        raise HTTPException(status_code=403, detail="Missing permission: tax.manage")
    org = await db.organisations.find_one({"id": ctx.org_id})
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    company = input.company or {}
    payroll = input.payroll or {}
    statutory = input.statutory or {}
    state = company.get("state") or org.get("state") or "KA"

    await db.organisations.update_one({"id": ctx.org_id}, {"$set": {
        "name": company.get("name") or org.get("name"),
        "address": company.get("address", org.get("address", "")),
        "city": company.get("city", org.get("city", "")),
        "state": state,
        "jurisdiction": company.get("jurisdiction", org.get("jurisdiction", "IN")),
        "payroll_settings": {
            "pay_frequency": payroll.get("pay_frequency", "monthly"),
            "pay_day": payroll.get("pay_day", "last-day"),
            "accept_unverified_statutory_values": bool(statutory.get("accept_unverified", False)),
        },
        "onboarded": True,
    }})

    for loc in input.locations:
        if loc.get("name"):
            await db.locations.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "name": loc["name"],
                "city": loc.get("city", ""), "state": loc.get("state", state),
                "municipality": loc.get("municipality", ""), "created_at": now(),
            })

    for establishment in input.statutory_establishments:
        if establishment.location_id and not await db.locations.find_one(
                {"id": establishment.location_id, "org_id": ctx.org_id}, {"_id": 1}):
            raise HTTPException(status_code=422, detail="Work location not found in this organisation")
        establishment_doc = establishment.model_dump(mode="json")
        establishment_doc.update({"id": new_id(), "org_id": ctx.org_id, "created_at": now()})
        await db.statutory_establishments.insert_one(establishment_doc)

    components = [
        {"code": "BASIC", "name": "Basic Salary", "calc": "pct_gross", "value": input.basic_pct,
         "taxable": True, "pf_applicable": True, "esi_applicable": True, "ctc_included": True},
        {"code": "HRA", "name": "House Rent Allowance", "calc": "pct_basic", "value": input.hra_pct,
         "taxable": True, "pf_applicable": False, "esi_applicable": True, "ctc_included": True},
        {"code": "SPECIAL", "name": "Special Allowance", "calc": "gross_balance", "value": 0,
         "taxable": True, "pf_applicable": False, "esi_applicable": True, "ctc_included": True},
    ]
    structure = {
        "id": new_id(), "org_id": ctx.org_id, "name": input.structure_name,
        "components": components, "created_at": now(),
    }
    await db.salary_structures.insert_one(structure)

    for lt in input.leave_types:
        if lt.get("code") and lt.get("name"):
            await db.leave_types.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "code": lt["code"], "name": lt["name"],
                "annual_quota": float(lt.get("annual_quota", 0)), "paid": bool(lt.get("paid", True)),
                "accrual": "monthly", "carry_forward": bool(lt.get("carry_forward", True)),
                "created_at": now(),
            })

    dept_cache: dict[str, str] = {}
    seq = await db.employees.count_documents({"org_id": ctx.org_id})
    created_ids: list[str] = []
    for seed in input.employees:
        seq += 1
        dept_name = (seed.department or "").strip()
        dept_id = ""
        if dept_name:
            if dept_name not in dept_cache:
                existing = await db.departments.find_one({"org_id": ctx.org_id, "name": dept_name})
                dept_id = existing["id"] if existing else new_id()
                if not existing:
                    await db.departments.insert_one({"id": dept_id, "org_id": ctx.org_id,
                                                     "name": dept_name, "created_at": now()})
                dept_cache[dept_name] = dept_id
            dept_id = dept_cache[dept_name]
        emp_id = new_id()
        await db.employees.insert_one({
            "id": emp_id, "org_id": ctx.org_id,
            "employee_code": f"EMP-{seq:04d}",
            "name": seed.name, "work_email": seed.email, "personal_email": None,
            "phone": seed.phone, "date_of_birth": None, "gender": None, "marital_status": None,
            "address": "", "city": "", "state": seed.state or state, "pin": "",
            "joining_date": seed.joining_date, "confirmation_date": None,
            "employment_type": "full_time", "department_id": dept_id, "department_name": dept_name,
            "designation": seed.designation or "", "grade": "", "location_name": "",
            "reporting_manager_id": None, "cost_centre": "", "status": "active",
            "exit_date": None, "exit_reason": None,
            "pan": None, "uan": None, "pf_number": None,
            "pf_applicable": seed.pf_applicable, "esi_number": None,
            "esi_applicable": seed.esi_applicable,
            "pt_applicable": True, "lwf_applicable": True,
            "tax_regime": seed.tax_regime,
            "bank_name": None, "bank_account": None, "ifsc": None, "account_holder": None,
            "emergency_contact_name": None, "emergency_contact_phone": None,
            "user_id": None, "created_at": now(),
        })
        if seed.tax_year_profile:
            await upsert_tax_profile(ctx.org_id, emp_id, seed.tax_year_profile, ctx.user)
        await db.salary_assignments.insert_one({
            "id": new_id(), "org_id": ctx.org_id, "employee_id": emp_id,
            "structure_id": structure["id"], "gross_monthly": seed.gross_monthly,
            "effective_from": seed.joining_date, "active": True, "created_at": now(),
        })
        lts = await db.leave_types.find({"org_id": ctx.org_id}).to_list(20)
        for lt in lts:
            await db.leave_balances.insert_one({
                "id": new_id(), "org_id": ctx.org_id, "employee_id": emp_id,
                "leave_type_id": lt["id"], "leave_code": lt["code"],
                "granted": lt["annual_quota"], "used": 0, "year": today_iso()[:4],
            })
        created_ids.append(emp_id)

    run_id = None
    if input.run_test_payroll and created_ids:
        fresh = await db.organisations.find_one({"id": ctx.org_id})
        run = await payroll_service.create_run(fresh, today_iso()[:7], ctx.user)
        run_id = run["id"]
        await payroll_service.calculate_run(run_id, ctx.user)

    await emit(ctx.org_id, "organisation.onboarded", actor=ctx.user, entity="organisation",
               entity_id=ctx.org_id, summary=f"Onboarding completed: {len(created_ids)} employees seeded")
    return {"ok": True, "employee_count": len(created_ids), "structure_id": structure["id"], "run_id": run_id}


@router.get("/jurisdictions")
async def jurisdictions():
    return list_jurisdictions()


@router.get("/org/roles")
async def roles(ctx: Context = Depends(require_perm("settings.manage"))):
    return [{"role": r, "permissions": permissions_for_role(r)} for r in ROLES]


class OrgUserIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: str
    employee_id: str | None = None


@router.get("/org/users")
async def org_users(ctx: Context = Depends(require_perm("users.manage"))):
    users = await db.users.find({"memberships.org_id": ctx.org_id},
                                {"password_hash": 0, "reset_token": 0}).to_list(500)
    return [{
        "id": u["id"], "name": u["name"], "email": u["email"],
        "role": next((m["role"] for m in u.get("memberships", []) if m["org_id"] == ctx.org_id), None),
        "employee_id": u.get("employee_id"), "mfa_enabled": u.get("mfa_enabled", False),
        "created_at": u.get("created_at"),
    } for u in users]


@router.post("/org/users")
async def create_org_user(input: OrgUserIn, ctx: Context = Depends(require_perm("users.manage"))):
    if input.role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role")
    email = input.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    if input.employee_id:
        emp = await db.employees.find_one({"id": input.employee_id, "org_id": ctx.org_id})
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found in this organisation")
    user = {
        "id": new_id(), "name": input.name, "email": email,
        "password_hash": hash_password(input.password),
        "memberships": [{"org_id": ctx.org_id, "role": input.role}],
        "employee_id": input.employee_id, "is_super_admin": False, "mfa_enabled": False,
        "created_at": now(),
    }
    await db.users.insert_one(user)
    if input.employee_id:
        await db.employees.update_one({"id": input.employee_id, "org_id": ctx.org_id},
                                     {"$set": {"user_id": user["id"]}})
    await emit(ctx.org_id, "user.created", actor=ctx.user, entity="user", entity_id=user["id"],
               summary=f"User {email} added with role {input.role}")
    return {"id": user["id"], "email": email, "role": input.role}


class RoleUpdate(BaseModel):
    role: str


@router.put("/org/users/{user_id}/role")
async def update_role(user_id: str, input: RoleUpdate, ctx: Context = Depends(require_perm("users.manage"))):
    if input.role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown role")
    res = await db.users.update_one(
        {"id": user_id, "memberships.org_id": ctx.org_id},
        {"$set": {"memberships.$.role": input.role}},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="User not found in this organisation")
    await emit(ctx.org_id, "permission.changed", actor=ctx.user, entity="user", entity_id=user_id,
               new={"role": input.role}, summary=f"Role changed to {input.role} for user {user_id[:8]}")
    return {"ok": True}
