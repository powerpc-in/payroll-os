"""Full & Final settlement statement (PDF) — fpdf2.

Mirrors the payslip generator's conventions: optional DejaVu for the rupee glyph,
explicit new_x/new_y on every cell, and an unverified-rules notice when any line was
computed from a rule marked 'Requires statutory verification'.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fpdf import FPDF

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
]


def _font() -> str | None:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


_ASCII_MAP = {"\u2022": "-", "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u00d7": "x",
              "\u20b9": "INR ", "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
              "\u00b7": "|", "\u2026": "..."}


def _ascii(text: str) -> str:
    """fpdf2's core fonts are latin-1 only. When the Unicode font is unavailable we
    transliterate instead of raising — a statement must always render."""
    for src, dst in _ASCII_MAP.items():
        text = text.replace(src, dst)
    return text.encode("ascii", "ignore").decode()


def build_ff_statement(org: dict, ff: dict) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(margin=16, auto=True)
    font_path = _font()
    if font_path:
        pdf.add_font("DejaVu", "", font_path)
        pdf.set_font("DejaVu", size=10)
        sym = "₹"
        bullet = "• "
    else:
        pdf.set_font("Helvetica", size=10)
        sym = "INR "
        bullet = "- "
    unicode_ok = bool(font_path)

    def T(text: str) -> str:
        return str(text) if unicode_ok else _ascii(str(text))

    pdf.add_page()

    def money(v: float) -> str:
        return f"{sym}{float(v or 0):,.2f}"

    def H(text: str, size: int = 10, style: str = "") -> None:
        pdf.set_font(pdf.font_family, style, size)
        pdf.cell(0, 7, T(text), new_x="LMARGIN", new_y="NEXT")

    def kv(label: str, value: str) -> None:
        pdf.set_font(pdf.font_family, "", 9)
        pdf.cell(45, 5, T(label), new_x="RIGHT", new_y="TOP")
        pdf.cell(0, 5, T(value), new_x="LMARGIN", new_y="NEXT")

    H(org.get("name", "Organisation"), 16, "B")
    pdf.set_font(pdf.font_family, "", 9)
    pdf.cell(0, 5, T(f"{org.get('address', '')} | {org.get('state_name', '') or org.get('city', '')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    H("Full & Final Settlement Statement", 13, "B")
    pdf.ln(1)

    kv("Employee", f"{ff.get('employee_name')} ({ff.get('employee_code') or '—'})")
    kv("Department", str(ff.get("department") or "—"))
    kv("Date of joining", str(ff.get("joining_date") or "—"))
    kv("Last working day", str(ff.get("last_working_day")))
    kv("Exit reason", str(ff.get("exit_reason") or "—"))
    kv("Status", str(ff.get("status", "draft")).upper())
    kv("Settlement ID", str(ff.get("id", ""))[:8])
    pdf.ln(2)

    if ff.get("computed_with_unverified_rules"):
        pdf.set_text_color(146, 64, 14)
        pdf.set_font(pdf.font_family, "", 8)
        pdf.multi_cell(0, 4.5, T("NOTICE: one or more amounts were computed from statutory rules "
                               "marked 'Requires statutory verification'. Figures are indicative "
                               "and must be verified before payout."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)

    def table(title: str, lines: list[dict], total_label: str, total: float) -> None:
        pdf.set_font(pdf.font_family, "B", 10)
        pdf.cell(0, 6, T(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.font_family, "", 8.5)
        pdf.set_fill_color(241, 245, 249)
        pdf.cell(60, 5.5, T("Component"), border=1, fill=True, new_x="RIGHT", new_y="TOP")
        pdf.cell(88, 5.5, T("How it was calculated"), border=1, fill=True, new_x="RIGHT", new_y="TOP")
        pdf.cell(30, 5.5, T("Amount"), border=1, fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
        if not lines:
            pdf.cell(178, 5.5, T("None"), border=1, new_x="LMARGIN", new_y="NEXT")
        for ln in lines:
            calc = str((ln.get("explanation") or {}).get("calculation") or "")[:62]
            pdf.cell(60, 5.5, T(str(ln.get("name"))[:38]), border=1, new_x="RIGHT", new_y="TOP")
            pdf.cell(88, 5.5, T(calc), border=1, new_x="RIGHT", new_y="TOP")
            pdf.cell(30, 5.5, money(ln.get("amount")), border=1, align="R",
                     new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.font_family, "B", 9)
        pdf.cell(148, 5.5, T(total_label), border=1, new_x="RIGHT", new_y="TOP")
        pdf.cell(30, 5.5, money(total), border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    table("A. Amounts payable", ff.get("payable", []), "Total payable (A)", ff.get("total_payable", 0))
    table("B. Recoveries & deductions", ff.get("recoveries", []), "Total recoveries (B)",
          ff.get("total_recoveries", 0))

    pdf.set_font(pdf.font_family, "", 9)
    pdf.cell(148, 5.5, T("C. Tax / TDS adjustment on settlement"), border=1, new_x="RIGHT", new_y="TOP")
    pdf.cell(30, 5.5, money(ff.get("tax_adjustment", 0)), border=1, align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.font_family, "B", 11)
    pdf.set_fill_color(15, 23, 42)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(148, 7, T("NET FINAL SETTLEMENT (A - B - C)"), border=1, fill=True,
             new_x="RIGHT", new_y="TOP")
    pdf.cell(30, 7, money(ff.get("net_settlement", 0)), border=1, fill=True, align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    pdf.set_font(pdf.font_family, "", 8)
    for note in [ff.get("gratuity_note"), ff.get("tax_adjustment_note"), *(ff.get("computation_notes") or [])]:
        if note:
            pdf.multi_cell(0, 4.2, T(f"{bullet}{note}"), new_x="LMARGIN", new_y="NEXT")
    if ff.get("notes"):
        pdf.multi_cell(0, 4.2, T(f"{bullet}Remarks: {ff['notes']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_text_color(100, 116, 139)
    pdf.multi_cell(0, 4, T("This statement is generated by an MVP payroll system and is not a "
                           "statutorily certified document. "
                           + datetime.now(timezone.utc).strftime("Generated %Y-%m-%d %H:%M UTC")),
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
