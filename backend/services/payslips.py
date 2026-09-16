"""Payslip PDF generation (fpdf2).

No system unicode font exists in the pod, so the ₹ glyph degrades to "INR" on
the core Helvetica font; if a DejaVu/Noto font is found it is embedded instead.
"""

from __future__ import annotations

import os

from fpdf import FPDF

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
]


def _font() -> str | None:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _money(pdf: FPDF, value: float) -> str:
    if pdf.font_family == "DejaVu":
        return f"₹{value:,.2f}"
    return f"INR {value:,.2f}"


def build_payslip(
    org: dict,
    run: dict,
    result: dict,
) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(margin=16, auto=True)
    font_path = _font()
    if font_path:
        pdf.add_font("DejaVu", "", font_path)
        pdf.set_font("DejaVu", size=10)
    else:
        pdf.set_font("Helvetica", size=10)
    pdf.add_page()

    def H(text: str, size: int = 10, style: str = "") -> None:
        pdf.set_font_size(size)
        pdf.set_font(pdf.font_family, style, size)
        pdf.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")

    # Header
    pdf.set_draw_color(15, 23, 42)
    pdf.set_line_width(0.6)
    pdf.cell(0, 2, "", border="B", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    H(org.get("name", "Organisation"), 16, "B")
    pdf.set_font_size(9)
    pdf.cell(0, 5, f"{org.get('address', '')} · {org.get('state_name', '')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Payslip · {run['period']} · {result['employee_snapshot']['name']}"
                   f" ({result['employee_snapshot'].get('employee_code') or ''})",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if result.get("computed_with_unverified_rules"):
        pdf.set_text_color(146, 64, 14)
        pdf.set_font_size(8)
        pdf.multi_cell(0, 5, "NOTICE: computed with statutory rules marked 'Requires statutory "
                             "verification'. Figures are indicative and must be verified before use.")
        pdf.set_text_color(0)
        pdf.ln(1)

    snap = result["employee_snapshot"]
    pdf.set_font_size(9)
    pdf.cell(95, 5, f"Employee: {snap['name']}", new_x="RIGHT", new_y="TOP")
    pdf.cell(95, 5, f"Department: {snap.get('department') or '—'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 5, f"Designation: {snap.get('designation') or '—'}", new_x="RIGHT", new_y="TOP")
    pdf.cell(95, 5, f"Location: {snap.get('location') or '—'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 5, f"PAN: {snap.get('pan_masked') or '—'}", new_x="RIGHT", new_y="TOP")
    pdf.cell(95, 5, f"Tax regime: {snap.get('tax_regime', '').title()}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 5, f"Paid days: {result['paid_days']:g} / {result['total_days']} (LOP {result['lop_days']:g})",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Earnings / deductions two-column table
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font_size(9)
    pdf.cell(95, 7, "Earnings", border=1, fill=True)
    pdf.cell(95, 7, "Deductions", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    earns = [(e["name"], e["amount"]) for e in result["earnings"]]
    deds = [(d["name"], d["amount"]) for d in result["deductions"]] + [("Total deductions", result["total_deductions"])]
    for i in range(max(len(earns), len(deds))):
        en, ea = earns[i] if i < len(earns) else ("", 0)
        dn, da = deds[i] if i < len(deds) else ("", 0)
        pdf.cell(62, 6, en[:38], border=1)
        pdf.cell(33, 6, _money(pdf, ea), border=1, align="R")
        pdf.cell(62, 6, dn[:38], border=1)
        pdf.cell(33, 6, _money(pdf, da), border=1, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)
    pdf.set_font_size(9)
    pdf.cell(95, 6, f"Gross earnings: {_money(pdf, result['gross_earnings'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 6, f"Net pay: {_money(pdf, result['net_pay'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 6, f"Employer cost: {_money(pdf, result['employer_cost'])}", new_x="LMARGIN", new_y="NEXT")

    if result["employer_contributions"]:
        pdf.ln(2)
        pdf.cell(95, 6, "Employer contributions (not deducted from net):", new_x="LMARGIN", new_y="NEXT")
        for c in result["employer_contributions"]:
            pdf.cell(157, 6, f"  · {c['name']}", new_x="RIGHT", new_y="TOP")
            pdf.cell(33, 6, _money(pdf, c["amount"]), align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    pdf.set_font_size(7)
    pdf.multi_cell(0, 4,
        "System-generated payslip. This MVP platform is not statutorily certified; where statutory "
        "values are marked 'Requires statutory verification' they must be independently confirmed. "
        f"Rule versions used: " + "; ".join(
            f"{r['rule_type']} v{r['version']} ({r.get('source') or 'n/a'})"
            + ("" if r.get('verified') else " [unverified]")
            for r in result.get("rule_refs", [])
        ) or "—")
    return bytes(pdf.output())
