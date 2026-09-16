"""Jurisdiction registry — the global backbone of the payroll platform.

Every country is a module. The CORE engine (payroll, salary, attendance, leave,
reports, auth, integrations) knows NOTHING country-specific; it resolves
jurisdiction metadata here and versioned statutory rules from the database.

A jurisdiction may be:
  status="active"               — statutory rules seeded and marked verified enough to compute
  status="architecture_ready"   — the module exists but has NO configured rules; it must
                                  never compute payroll. Any value would require independent
                                  statutory verification first.
"""

IN_STATES: list[dict[str, str]] = [
    {"code": "KA", "name": "Karnataka"}, {"code": "MH", "name": "Maharashtra"},
    {"code": "DL", "name": "Delhi"}, {"code": "TN", "name": "Tamil Nadu"},
    {"code": "TG", "name": "Telangana"}, {"code": "AP", "name": "Andhra Pradesh"},
    {"code": "GJ", "name": "Gujarat"}, {"code": "RJ", "name": "Rajasthan"},
    {"code": "UP", "name": "Uttar Pradesh"}, {"code": "WB", "name": "West Bengal"},
    {"code": "KL", "name": "Kerala"}, {"code": "MP", "name": "Madhya Pradesh"},
    {"code": "PB", "name": "Punjab"}, {"code": "HR", "name": "Haryana"},
    {"code": "BR", "name": "Bihar"}, {"code": "OR", "name": "Odisha"},
]

_JURISDICTIONS: dict[str, dict] = {
    "IN": {
        "code": "IN", "name": "India", "currency": "INR", "currency_symbol": "₹",
        "status": "active", "tax_year_start_month": 4, "tax_year_label": "April–March",
        "default_pay_frequency": "monthly",
        "states": IN_STATES,
        "rule_types": [
            "income_tax_old_regime", "income_tax_new_regime", "provident_fund",
            "employee_state_insurance", "professional_tax", "lwf", "gratuity", "bonus",
        ],
    },
    "GB": {
        "code": "GB", "name": "United Kingdom (incl. London)", "currency": "GBP",
        "currency_symbol": "£", "status": "architecture_ready",
        "tax_year_start_month": 4, "tax_year_label": "April–April",
        "default_pay_frequency": "monthly", "states": [],
        "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
    "US": {
        "code": "US", "name": "United States", "currency": "USD", "currency_symbol": "$",
        "status": "architecture_ready", "tax_year_start_month": 1,
        "tax_year_label": "January–December", "default_pay_frequency": "biweekly",
        "states": [], "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
    "GH": {
        "code": "GH", "name": "Ghana", "currency": "GHS", "currency_symbol": "₵",
        "status": "architecture_ready", "tax_year_start_month": 1,
        "tax_year_label": "January–December", "default_pay_frequency": "monthly",
        "states": [], "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
    "SG": {
        "code": "SG", "name": "Singapore", "currency": "SGD", "currency_symbol": "S$",
        "status": "architecture_ready", "tax_year_start_month": 1,
        "tax_year_label": "January–December", "default_pay_frequency": "monthly",
        "states": [], "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
    "AU": {
        "code": "AU", "name": "Australia", "currency": "AUD", "currency_symbol": "A$",
        "status": "architecture_ready", "tax_year_start_month": 7,
        "tax_year_label": "July–June", "default_pay_frequency": "monthly",
        "states": [], "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
    "AE": {
        "code": "AE", "name": "United Arab Emirates", "currency": "AED", "currency_symbol": "د.إ",
        "status": "architecture_ready", "tax_year_start_month": 1,
        "tax_year_label": "January–December", "default_pay_frequency": "monthly",
        "states": [], "rule_types": [],
        "note": "Jurisdiction module ready. No statutory rules configured — requires statutory verification before activation.",
    },
}


def get_jurisdiction(code: str) -> dict | None:
    return _JURISDICTIONS.get(code)


def list_jurisdictions() -> list[dict]:
    return list(_JURISDICTIONS.values())


def is_active(code: str) -> bool:
    j = _JURISDICTIONS.get(code)
    return bool(j and j["status"] == "active")
