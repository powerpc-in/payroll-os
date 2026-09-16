"""Demo data seeder — a fictional company with a fully processed payroll run.

    cd /app/backend && python seed.py

Idempotent: re-running wipes and rebuilds ONLY the demo organisation's data.
All people, emails and identifiers are fictional. Statutory values are stored as
versioned rules marked verified=False ('Requires statutory verification') and the
demo org explicitly opts into computing with them — the UI and payslips show the
verification badge everywhere.
"""

import asyncio
import calendar
from datetime import date, datetime, timedelta, timezone

from lib.auth import hash_password, new_id
from lib.db import client, db, ensure_indexes
from services import payroll_service

ORG_NAME = "Kaveri Textiles Pvt Ltd"
DOMAIN = "kaveritextiles.example"
PASSWORD = "Demo@12345"
EFF_FROM = "2025-04-01"  # FY 2025-26 rules, left open-ended (versioned; never silently invented)
SOURCE_DATE = "2025-03-31"

SURCHARGE = [
    {"above": 5000000, "rate": 0.10}, {"above": 10000000, "rate": 0.15},
    {"above": 20000000, "rate": 0.20}, {"above": 50000000, "rate": 0.25},
]

STATUTORY_RULES = [
    {"rule_type": "income_tax_new_regime", "state": None, "source": "Income-tax Act, 1961 §115BAC (Finance Act 2025)",
     "params": {
         "slabs": [{"up_to": 400000, "rate": 0}, {"up_to": 800000, "rate": 0.05},
                   {"up_to": 1200000, "rate": 0.10}, {"up_to": 1600000, "rate": 0.15},
                   {"up_to": 2000000, "rate": 0.20}, {"up_to": 2400000, "rate": 0.25},
                   {"up_to": None, "rate": 0.30}],
         "rebate": {"taxable_limit": 1200000, "max_rebate": 60000},
         "standard_deduction": 75000, "surcharge": SURCHARGE, "cess_rate": 0.04}},
    {"rule_type": "income_tax_old_regime", "state": None, "source": "Income-tax Act, 1961 (old regime)",
     "params": {
         "slabs": [{"up_to": 250000, "rate": 0}, {"up_to": 500000, "rate": 0.05},
                   {"up_to": 1000000, "rate": 0.20}, {"up_to": None, "rate": 0.30}],
         "rebate": {"taxable_limit": 500000, "max_rebate": 12500},
         "standard_deduction": 50000, "cap_80c": 150000, "cap_80d": 25000,
         "surcharge": SURCHARGE, "cess_rate": 0.04}},
    {"rule_type": "provident_fund", "state": None, "source": "EPF Act, 1952 / EPF Scheme, 1952",
     "params": {"employee_rate": 0.12, "employer_rate": 0.12, "eps_rate": 0.0833, "wage_ceiling": None}},
    {"rule_type": "employee_state_insurance", "state": None, "source": "ESI Act, 1948",
     "params": {"employee_rate": 0.0075, "employer_rate": 0.0325, "gross_limit": 21000}},
    {"rule_type": "gratuity", "state": None, "source": "Payment of Gratuity Act, 1972 §4",
     "params": {"eligibility_years": 5, "formula": "15/26 × last drawn basic × years"}},
    {"rule_type": "bonus", "state": None, "source": "Payment of Bonus Act, 1965",
     "params": {"min_bonus_pct": 8.33, "max_bonus_pct": 20, "eligibility_wage_limit": 21000}},
    {"rule_type": "professional_tax", "state": "KA", "source": "Karnataka State Tax on Professions Act, 1976",
     "params": {"slabs": [{"min": 25000, "amount": 200}]}},
    {"rule_type": "professional_tax", "state": "MH", "source": "Maharashtra State Tax on Professions Act, 1975",
     "params": {"slabs": [{"min": 7500, "amount": 200}]}},
    {"rule_type": "professional_tax", "state": "DL", "source": "Delhi Tax on Professions Act (slabs)",
     "params": {"slabs": [{"min": 20000, "amount": 200}]}},
    {"rule_type": "professional_tax", "state": "TG", "source": "Telangana State Tax on Professions Act",
     "params": {"slabs": [{"min": 15000, "amount": 200}]}},
    {"rule_type": "lwf", "state": "KA", "source": "Karnataka LWF Act",
     "params": {"employee": 20, "employer": 40}},
    {"rule_type": "lwf", "state": "MH", "source": "Maharashtra LWF Act",
     "params": {"employee": 12, "employer": 36}},
    {"rule_type": "lwf", "state": "DL", "source": "Delhi LWF rules",
     "params": {"employee": 0.75, "employer": 22.5}},
    {"rule_type": "lwf", "state": "TG", "source": "Telangana LWF Act",
     "params": {"employee": 20, "employer": 20}},
]

# (name, email, phone, department, designation, state, gross, regime, pf, esi, doj)
EMPLOYEES = [
    ("Arjun Mehta", "arjun", "9820011001", "Engineering", "Senior Engineer", "KA", 95000, "new", True, False, "2023-06-12"),
    ("Diya Sharma", "diya", "9820011002", "Engineering", "Engineer", "KA", 62000, "new", True, False, "2024-02-01"),
    ("Rohan Iyer", "rohan", "9820011003", "Sales", "Sales Executive", "MH", 28000, "old", True, True, "2023-11-20"),
    ("Kavya Nair", "kavya", "9820011004", "Sales", "Sales Manager", "MH", 88000, "new", True, False, "2022-08-15"),
    ("Aditya Kulkarni", "aditya", "9820011005", "Finance", "Accountant", "MH", 35000, "old", True, True, "2024-07-01"),
    ("Meera Joshi", "meera", "9820011006", "Finance", "Finance Lead", "DL", 105000, "new", True, False, "2021-05-10"),
    ("Vihaan Kapoor", "vihaan", "9820011007", "Operations", "Ops Executive", "DL", 19500, "old", True, True, "2024-09-23"),
    ("Ananya Reddy", "ananya", "9820011008", "Engineering", "QA Engineer", "TG", 45000, "new", True, False, "2023-03-27"),
    ("Kabir Singh", "kabir", "9820011009", "Operations", "Warehouse Lead", "DL", 32000, "old", True, True, "2022-12-05"),
    ("Isha Chawla", "isha", "9820011010", "People Ops", "HR Executive", "KA", 30000, "new", True, True, "2024-11-11"),
    ("Dev Patel", "dev", "9820011011", "Sales", "Sales Associate", "RJ", 24000, "new", True, False, "2025-01-06"),
    ("Tara Pillai", "tara", "9820011012", "Engineering", "Intern", "KA", 18000, "new", False, True, "2025-02-03"),
]

DECLARATIONS = {
    "Rohan Iyer": {"deduction_80c": 150000, "deduction_80d": 12000, "annual_rent_paid": 144000, "metro": False},
    "Aditya Kulkarni": {"deduction_80c": 90000, "deduction_80d": 8000, "annual_rent_paid": 0, "metro": False},
    "Vihaan Kapoor": {"deduction_80c": 40000, "deduction_80d": 5000, "annual_rent_paid": 72000, "metro": False},
    "Kabir Singh": {"deduction_80c": 120000, "deduction_80d": 10000, "annual_rent_paid": 0, "metro": False},
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def prev_period() -> str:
    today = date.today()
    first = today.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y-%m")


async def wipe(org_id: str) -> None:
    collections = ["employees", "departments", "locations", "designations", "cost_centres",
                   "salary_structures", "salary_assignments", "salary_components",
                   "payroll_runs", "payroll_employees", "payroll_inputs",
                   "attendance", "leave_types", "leave_balances", "leave_requests",
                   "reimbursements", "loans", "loan_repayments", "documents", "ffs",
                   "webhooks", "webhook_deliveries", "notifications", "audit_logs",
                   "statutory_rules", "tax_declarations", "saved_reports",
                   "integration_connections", "sync_jobs", "sync_logs"]
    for c in collections:
        await db[c].delete_many({"org_id": org_id})
    await db.users.delete_many({"memberships.org_id": org_id})
    await db.organisations.delete_one({"id": org_id})


async def main() -> None:
    await ensure_indexes()
    old = await db.organisations.find_one({"name": ORG_NAME})
    if old:
        await wipe(old["id"])

    org_id = new_id()
    org = {
        "id": org_id, "name": ORG_NAME, "jurisdiction": "IN", "currency": "INR",
        "address": "Plot 14, Peenya Industrial Area", "city": "Bengaluru", "state": "KA",
        "onboarded": True,
        "payroll_settings": {"pay_frequency": "monthly", "pay_day": "last-working-day",
                             "accept_unverified_statutory_values": True},
        "created_at": now(),
    }
    await db.organisations.insert_one(org)

    # --- statutory rules (versioned, unverified — requires statutory verification) ---
    for spec in STATUTORY_RULES:
        await db.statutory_rules.insert_one({
            "id": new_id(), "org_id": org_id, "jurisdiction": "IN",
            "rule_type": spec["rule_type"], "state": spec["state"], "params": spec["params"],
            "effective_from": EFF_FROM, "effective_to": None, "version": 1,
            "source": spec["source"], "source_date": SOURCE_DATE, "verified": False,
            "active": True, "notes": "Demo seed — every value requires statutory verification before production use.",
            "created_by": "seed", "created_at": now(),
        })

    # --- users (all fictional; password Demo@12345) ---
    def mk_user(name: str, email: str, role: str, employee_id: str | None = None) -> dict:
        return {"id": new_id(), "name": name, "email": f"{email}@{DOMAIN}",
                "password_hash": hash_password(PASSWORD),
                "memberships": [{"org_id": org_id, "role": role}],
                "employee_id": employee_id, "is_super_admin": False, "mfa_enabled": False,
                "created_at": now()}

    users = [
        mk_user("Priya Nair", "admin", "COMPANY_ADMIN"),
        mk_user("Rahul Verma", "payroll", "PAYROLL_ADMIN"),
        mk_user("Sana Iqbal", "hr", "HR_ADMIN"),
        mk_user("Vikram Rao", "finance", "FINANCE"),
        mk_user("Arjun Mehta", "manager", "MANAGER"),
        mk_user("Diya Sharma", "employee", "EMPLOYEE"),
    ]
    for u in users:
        await db.users.insert_one(u)

    # --- masters ---
    dept_names = ["Engineering", "Sales", "Finance", "Operations", "People Ops"]
    dept_ids = {}
    for name in dept_names:
        dept_id = new_id()
        dept_ids[name] = dept_id
        await db.departments.insert_one({"id": dept_id, "org_id": org_id, "name": name, "created_at": now()})
    for loc_name, state in [("Bengaluru HQ", "KA"), ("Mumbai Office", "MH"), ("Delhi Depot", "DL")]:
        await db.locations.insert_one({"id": new_id(), "org_id": org_id, "name": loc_name,
                                       "city": loc_name.split()[0], "state": state, "created_at": now()})

    # --- leave types + balances ---
    leave_types = [("CL", "Casual Leave", 12), ("EL", "Earned Leave", 15), ("SL", "Sick Leave", 8)]
    lt_ids = {}
    for code, name, quota in leave_types:
        lt_id = new_id()
        lt_ids[code] = lt_id
        await db.leave_types.insert_one({
            "id": lt_id, "org_id": org_id, "code": code, "name": name, "annual_quota": quota,
            "paid": True, "accrual": "monthly", "carry_forward": True, "created_at": now()})

    # --- salary structure ---
    structure = {
        "id": new_id(), "org_id": org_id, "name": "Standard India Structure",
        "components": [
            {"code": "BASIC", "name": "Basic Salary", "calc": "pct_gross", "value": 40,
             "taxable": True, "pf_applicable": True, "esi_applicable": True, "ctc_included": True},
            {"code": "HRA", "name": "House Rent Allowance", "calc": "pct_basic", "value": 50,
             "taxable": True, "pf_applicable": False, "esi_applicable": True, "ctc_included": True},
            {"code": "SPECIAL", "name": "Special Allowance", "calc": "gross_balance", "value": 0,
             "taxable": True, "pf_applicable": False, "esi_applicable": True, "ctc_included": True},
        ],
        "created_at": now(),
    }
    await db.salary_structures.insert_one(structure)

    # --- employees ---
    emp_ids: dict[str, str] = {}
    year = int(prev_period()[:4])
    for i, (name, email, phone, dept, desig, state, gross, regime, pf, esi, doj) in enumerate(EMPLOYEES):
        emp_id = new_id()
        emp_ids[name] = emp_id
        await db.employees.insert_one({
            "id": emp_id, "org_id": org_id, "employee_code": f"EMP-{i + 1:04d}",
            "name": name, "work_email": f"{email}@{DOMAIN}", "personal_email": None,
            "phone": phone, "date_of_birth": f"19{85 + (i % 10)}-0{1 + i % 9}-1{i % 9}",
            "gender": ["male", "female"][i % 2], "marital_status": ["single", "married"][i % 2],
            "address": f"{10 + i} Fictional Layout", "city": "Bengaluru", "state": state, "pin": "560013",
            "joining_date": doj, "confirmation_date": None, "employment_type": "full_time",
            "department_id": dept_ids.get(dept, ""), "department_name": dept, "designation": desig,
            "grade": f"L{1 + i % 5}", "location_name": "Bengaluru HQ", "reporting_manager_id": None,
            "cost_centre": f"CC-{100 + i % 3}", "status": "active", "exit_date": None, "exit_reason": None,
            "pan": f"ABC{i % 10}23{i}F{chr(65 + i)}", "uan": f"101{3000000 + i * 7}",
            "pf_number": f"KA/990{100 + i}", "pf_applicable": pf,
            "esi_number": f"3100123456{i:02d}" if esi else None, "esi_applicable": esi,
            "pt_applicable": True, "lwf_applicable": True, "tax_regime": regime,
            "bank_name": ["HDFC Bank", "ICICI Bank", "State Bank of India"][i % 3],
            "bank_account": f"50100{200000 + i * 137}", "ifsc": ["HDFC0000123", "ICIC0001234", "SBIN0004567"][i % 3],
            "account_holder": name, "emergency_contact_name": "Fictional Relative",
            "emergency_contact_phone": "9800000000", "user_id": None, "created_at": now(),
        })
        await db.salary_assignments.insert_one({
            "id": new_id(), "org_id": org_id, "employee_id": emp_id,
            "structure_id": structure["id"], "gross_monthly": gross,
            "effective_from": doj, "active": True, "created_at": now(),
        })
        for code, _, quota in leave_types:
            await db.leave_balances.insert_one({
                "id": new_id(), "org_id": org_id, "employee_id": emp_id,
                "leave_type_id": lt_ids[code], "leave_code": code,
                "granted": quota, "used": 2 if (name == "Diya Sharma" and code == "CL") else 0,
                "year": str(year),
            })
        for key, val in DECLARATIONS.get(name, {}).items():
            pass
        if name in DECLARATIONS:
            await db.tax_declarations.insert_one({"id": new_id(), "org_id": org_id,
                                                  "employee_id": emp_id, **DECLARATIONS[name]})

    # reporting manager: Arjun manages the Engineering folks
    await db.employees.update_one({"id": emp_ids["Arjun Mehta"]}, {"$set": {"user_id": users[4]["id"]}})
    await db.employees.update_one({"id": emp_ids["Diya Sharma"]}, {"$set": {"user_id": users[5]["id"]}})
    await db.users.update_one({"id": users[4]["id"]}, {"$set": {"employee_id": emp_ids["Arjun Mehta"]}})
    await db.users.update_one({"id": users[5]["id"]}, {"$set": {"employee_id": emp_ids["Diya Sharma"]}})
    for name in ("Diya Sharma", "Ananya Reddy", "Tara Pillai"):
        await db.employees.update_one({"id": emp_ids[name]},
                                      {"$set": {"reporting_manager_id": emp_ids["Arjun Mehta"]}})

    # --- attendance for the previous month (feeds the seeded payroll run) ---
    period = prev_period()
    y, m = int(period[:4]), int(period[5:7])
    days_in_month = calendar.monthrange(y, m)[1]
    for i, (name, *_rest) in enumerate(EMPLOYEES):
        for d in range(1, days_in_month + 1):
            day = date(y, m, d)
            if day.weekday() == 6:  # Sunday = weekly off
                status, ot = "weekly_off", 0
            elif (i + d) % 23 == 0:
                status, ot = "absent", 0
            elif (i + d) % 19 == 0:
                status, ot = "paid_leave", 0
            elif (i + d) % 29 == 0:
                status, ot = "half_day", 0
            else:
                status, ot = "present", 2 if (i + d) % 11 == 0 else 0
            await db.attendance.insert_one({
                "id": new_id(), "org_id": org_id, "employee_id": emp_ids[name],
                "date": day.isoformat(), "status": status, "days": 1,
                "overtime_hours": ot, "period": period, "created_at": now(),
            })
    # Diya's approved CL (2 days) already reflected in attendance + balance

    # --- reimbursements ---
    await db.reimbursements.insert_many([
        {"id": new_id(), "org_id": org_id, "employee_id": emp_ids["Rohan Iyer"],
         "employee_name": "Rohan Iyer", "category": "travel", "amount": 5200,
         "description": "Client visit — fictional trip", "date": f"{period}-12", "taxable": False,
         "status": "approved", "approved_amount": 4500, "decided_by": users[2]["email"],
         "paid_run_id": None, "created_at": now()},
        {"id": new_id(), "org_id": org_id, "employee_id": emp_ids["Aditya Kulkarni"],
         "employee_name": "Aditya Kulkarni", "category": "internet", "amount": 1200,
         "description": "Broadband reimbursement", "date": f"{period}-14", "taxable": True,
         "status": "pending", "approved_amount": 0, "decided_by": None,
         "paid_run_id": None, "created_at": now()},
    ])

    # --- loan for Diya (EMI lands in the seeded run) ---
    from routers.loans import build_schedule
    emi, schedule = build_schedule(60000, 9, 12, period)
    await db.loans.insert_one({
        "id": new_id(), "org_id": org_id, "employee_id": emp_ids["Diya Sharma"],
        "employee_name": "Diya Sharma", "name": "Education loan (fictional)",
        "principal": 60000, "interest_rate": 9, "tenure_months": 12, "start_period": period,
        "emi": emi, "schedule": schedule, "outstanding": 60000, "status": "active",
        "deduct_from_payroll": True, "created_at": now(),
    })

    # --- a pending leave request for the approvals queue ---
    await db.leave_requests.insert_one({
        "id": new_id(), "org_id": org_id, "employee_id": emp_ids["Vihaan Kapoor"],
        "employee_name": "Vihaan Kapoor", "leave_type_id": lt_ids["SL"], "leave_code": "SL",
        "leave_name": "Sick Leave", "paid": True, "unpaid": False,
        "from_date": f"{period}-20", "to_date": f"{period}-20", "days": 1,
        "reason": "Fictional fever", "status": "pending", "created_at": now(),
        "decided_by": None, "decided_at": None,
    })

    # --- webhook sample (inactive — points at a fictional URL) ---
    await db.webhooks.insert_one({
        "id": new_id(), "org_id": org_id, "name": "Demo receiver (inactive)",
        "url": "https://example.com/payroll-webhooks", "secret": "demo-secret-0001",
        "events": ["payroll.approved", "payroll.locked", "employee.created"], "active": False,
        "created_at": now(),
    })

    # --- saved report sample ---
    await db.saved_reports.insert_one({
        "id": new_id(), "org_id": org_id, "name": "Department payroll (last run)",
        "config": {"dataset": "department_payroll", "period_from": period, "period_to": period,
                   "group_by": "department"},
        "created_by": users[0]["email"], "created_at": now(),
    })

    # --- run the previous month's payroll end-to-end (locked history for payslips) ---
    fresh = await db.organisations.find_one({"id": org_id})
    run = await payroll_service.create_run(fresh, period, {"email": users[0]["email"], "id": users[0]["id"]})
    run = await payroll_service.calculate_run(run["id"], {"email": users[0]["email"], "id": users[0]["id"]})
    print(f"calculated run {period}: {run['totals']}")
    await db.payroll_runs.update_one({"id": run["id"]}, {"$set": {"status": "approved"}})
    await db.payroll_employees.update_many({"run_id": run["id"]}, {"$set": {"run_status": "approved"}})
    await db.payroll_runs.update_one({"id": run["id"]}, {"$set": {"status": "locked", "payslips_generated": True}})
    await db.payroll_employees.update_many({"run_id": run["id"]}, {"$set": {"run_status": "locked"}})
    # lock side effects: loan repayment + reimbursements paid
    loans = await db.loans.find({"org_id": org_id, "status": "active"}).to_list(10)
    for loan in loans:
        sched = next((r for r in loan.get("schedule", []) if r["period"] == period), None)
        if sched:
            await db.loan_repayments.insert_one({
                "id": new_id(), "org_id": org_id, "loan_id": loan["id"],
                "employee_id": loan["employee_id"], "period": period, "emi": sched["emi"],
                "principal": sched["principal"], "interest": sched["interest"],
                "paid_via": f"payroll:{run['id']}", "created_at": now()})
            await db.loans.update_one({"id": loan["id"]},
                                      {"$set": {"outstanding": round(loan["outstanding"] - sched["principal"], 2)}})
    await db.reimbursements.update_many(
        {"org_id": org_id, "status": "approved", "paid_run_id": None},
        {"$set": {"paid_run_id": run["id"], "status": "paid"}})

    print("Seed complete.")
    print(f"  Company: {ORG_NAME}")
    print(f"  Logins (password {PASSWORD}):")
    for u in users:
        print(f"    {u['email']}  ({u['memberships'][0]['role']})")
    print(f"  Employees: {len(EMPLOYEES)} · processed payroll period: {period}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
