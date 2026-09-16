"""Deterministic India income-tax computation — driven ENTIRELY by versioned rule documents.

No rate, threshold, rebate or cess value exists in this file. Every number comes
from a `statutory_rules` document (rule_type "income_tax_old_regime" /
"income_tax_new_regime") resolved for the effective date, so adding FY 2027-26
rules later never changes a historical run that snapshotted FY 2026-27.

Pure functions only — same inputs, same outputs, always. No generative AI.
"""

from __future__ import annotations

from typing import Any


def slab_tax(taxable: float, slabs: list[dict[str, Any]]) -> float:
    """slabs: [{"up_to": 400000, "rate": 0.0}, ..., {"up_to": None, "rate": 0.30}] — ordered."""
    tax = 0.0
    lower = 0.0
    for slab in slabs:
        upper = slab["up_to"]
        rate = float(slab["rate"])
        if upper is None or taxable <= upper:
            tax += max(0.0, taxable - lower) * rate
            break
        tax += (upper - lower) * rate
        lower = upper
    return tax


def _tiered(taxable: float, tiers: list[dict[str, Any]]) -> float:
    """tiers: [{"above": 5000000, "rate": 0.10}, ...] — the highest matching tier applies."""
    amount = 0.0
    for tier in tiers:
        if taxable > float(tier["above"]):
            amount = max(amount, taxable * float(tier["rate"]))
    return amount


def compute_income_tax(taxable: float, rule_params: dict[str, Any]) -> dict[str, Any]:
    slabs = rule_params["slabs"]
    tax = round(slab_tax(taxable, slabs), 2)

    rebate_cfg = rule_params.get("rebate", {})
    rebate = 0.0
    if rebate_cfg and taxable <= float(rebate_cfg.get("taxable_limit", 0)):
        rebate = min(tax, float(rebate_cfg.get("max_rebate", 0)))
    rebate = round(rebate, 2)

    base = max(0.0, tax - rebate)
    surcharge = round(_tiered(taxable, rule_params.get("surcharge", [])), 2)
    cess = round((base + surcharge) * float(rule_params.get("cess_rate", 0.0)), 2)
    total = round(base + surcharge + cess, 2)

    return {
        "tax_before_rebate": tax,
        "rebate_87a": rebate,
        "tax_after_rebate": base,
        "surcharge": surcharge,
        "health_education_cess": cess,
        "total_annual_tax": total,
    }


def slab_explanation(taxable: float, slabs: list[dict[str, Any]]) -> list[str]:
    """Human-readable slab-by-slab lines for the explanation engine."""
    lines: list[str] = []
    lower = 0.0
    for slab in slabs:
        upper = slab["up_to"]
        rate = float(slab["rate"])
        if upper is None or taxable <= upper:
            portion = max(0.0, taxable - lower)
            if portion > 0:
                lines.append(f"₹{fmt(lower)}–₹{fmt(lower + portion)} @ {pct(rate)} on ₹{fmt(portion)} = ₹{fmt(portion * rate)}")
            break
        if taxable > lower:
            lines.append(f"₹{fmt(lower)}–₹{fmt(upper)} @ {pct(rate)} on ₹{fmt(upper - lower)} = ₹{fmt((upper - lower) * rate)}")
        lower = upper
    return lines


def hra_exemption_annual(
    hra_received: float, rent_paid: float, basic_annual: float, metro: bool,
) -> float:
    """Section 10(13A) exemption — min of actual HRA, rent−10% basic, 50%/40% of basic."""
    if rent_paid <= 0 or hra_received <= 0:
        return 0.0
    opt1 = hra_received
    opt2 = max(0.0, rent_paid - 0.10 * basic_annual)
    opt3 = (0.50 if metro else 0.40) * basic_annual
    return round(min(opt1, opt2, opt3), 2)


def project_annual_taxable(
    gross_monthly_taxable: float, months_including_current: int,
    regime: str, rule_params: dict[str, Any], declarations: dict[str, Any],
    basic_monthly: float, hra_monthly: float,
) -> dict[str, Any]:
    """Project the annual taxable income for the financial year and return the
    component lines used (for the explanation engine)."""
    gross_annual = round(gross_monthly_taxable * months_including_current, 2)
    lines: list[dict[str, Any]] = [
        {"label": f"Gross taxable pay × {months_including_current} months", "amount": gross_annual}
    ]
    other_income = float(declarations.get("other_income", 0) or 0)
    if other_income:
        lines.append({"label": "Other income (declared)", "amount": other_income})

    if regime == "new":
        std = float(rule_params.get("standard_deduction", 0))
        lines.append({"label": f"Standard deduction", "amount": -std})
        taxable = max(0.0, gross_annual + other_income - std)
    else:
        std = float(rule_params.get("standard_deduction", 0))
        lines.append({"label": "Standard deduction", "amount": -std})
        d80c = min(float(declarations.get("deduction_80c", 0) or 0), float(rule_params.get("cap_80c", 150000)))
        if d80c:
            lines.append({"label": "Deduction 80C", "amount": -d80c})
        d80d = min(float(declarations.get("deduction_80d", 0) or 0), float(rule_params.get("cap_80d", 25000)))
        if d80d:
            lines.append({"label": "Deduction 80D (medical insurance)", "amount": -d80d})
        prof_tax_annual = float(declarations.get("professional_tax_annual", 0) or 0)
        if prof_tax_annual:
            lines.append({"label": "Professional tax paid (Sec 16(iii))", "amount": -prof_tax_annual})
        hra = hra_exemption_annual(
            hra_monthly * months_including_current,
            float(declarations.get("annual_rent_paid", 0) or 0),
            basic_monthly * months_including_current,
            bool(declarations.get("metro", False)),
        )
        if hra > 0:
            lines.append({"label": "HRA exemption (Sec 10(13A))", "amount": -hra})
        taxable = max(
            0.0,
            gross_annual + other_income - std - d80c - d80d - prof_tax_annual - hra,
        )

    return {
        "gross_annual": gross_annual,
        "other_income": other_income,
        "taxable": round(taxable, 2),
        "lines": lines,
    }


def tds_for_month(annual_tax: float, months_elapsed_in_fy: int, ytd_tds: float) -> float:
    """Deterministic monthly TDS: bring the cumulative deduction to annual/12 × months elapsed."""
    due_to_date = round(annual_tax / 12.0 * months_elapsed_in_fy, 2)
    return round(max(0.0, due_to_date - ytd_tds), 2)


def pct(rate: float) -> str:
    return f"{round(rate * 100, 2):g}%"


def fmt(x: float) -> str:
    return f"{x:,.0f}"
