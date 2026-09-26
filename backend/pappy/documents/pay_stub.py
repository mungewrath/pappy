"""Pay stub PDF generator (design-doc.md §5.4).

Renders a professional, itemized pay stub for a finalized pay run using
`reportlab`. Washington requires an itemized statement each pay period;
the YTD columns also make the FSA receipt trivially defensible (§6.3).

The generator takes flat string arguments — it does no I/O or model
dependencies, keeping it trivially testable.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_STYLES = getSampleStyleSheet()
_TITLE_STYLE = ParagraphStyle(
    "PayStubTitle",
    parent=_STYLES["Title"],
    fontSize=16,
    spaceAfter=6,
)
_HEADER_STYLE = ParagraphStyle(
    "PayStubHeader",
    parent=_STYLES["Heading2"],
    fontSize=11,
    spaceAfter=4,
    spaceBefore=8,
)
_NORMAL = _STYLES["Normal"]
_SMALL = ParagraphStyle(
    "PayStubSmall",
    parent=_NORMAL,
    fontSize=8,
    textColor=colors.grey,
)
_BOLD = ParagraphStyle(
    "PayStubBold",
    parent=_NORMAL,
    fontName="Helvetica-Bold",
)


def _fmt(val: str | None, *, prefix: str = "$") -> str:
    if val is None:
        return "\u2014"
    d = Decimal(val)
    return f"{prefix}{d:,.2f}"


def _fmt_or_dash(val: str | None) -> str:
    if val is None:
        return "\u2014"
    return _fmt(val)


def _fmt_hours(val: str) -> str:
    return f"{Decimal(val):.1f}"


def _withholding_row(
    label: str,
    current: str | None,
    ytd: str | None,
) -> list[object]:
    return [
        Paragraph(label, _NORMAL),
        Paragraph(_fmt(current), _NORMAL),
        Paragraph(_fmt_or_dash(ytd), _NORMAL),
    ]


def _format_address(
    line1: str, line2: str | None, city: str, state: str, zip_code: str
) -> str:
    lines = [line1]
    if line2:
        lines.append(line2)
    lines.append(f"{city}, {state} {zip_code}")
    return "<br/>".join(lines)


def generate_pay_stub_pdf(
    *,
    employer_name: str,
    employer_ein: str,
    employer_address_line1: str,
    employer_address_city: str,
    employer_address_state: str,
    employer_address_zip: str,
    employee_name: str,
    employee_address_line1: str,
    employee_address_city: str,
    employee_address_state: str,
    employee_address_zip: str,
    employee_hire_date: str,
    period_start: str,
    period_end: str,
    pay_date: str,
    regular_hours: str,
    overtime_hours: str,
    other_paid_hours: str,
    unpaid_hours: str,
    hourly_rate: str,
    straight_time_pay: str,
    overtime_premium_pay: str,
    gross: str,
    withholding_current: dict[str, str],
    total_withholding_current: str,
    net_pay_current: str,
    employer_address_line2: str | None = None,
    employee_address_line2: str | None = None,
    effective_overtime_rate: str | None = None,
    overtime_workweek: str | None = None,
    gross_ytd: str | None = None,
    withholding_ytd: dict[str, str] | None = None,
    total_withholding_ytd: str | None = None,
    net_pay_ytd: str | None = None,
) -> bytes:
    """Generate a pay stub PDF and return the raw bytes.

    All data is passed in — this function does no database or S3 I/O.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )

    elements: list[Flowable] = []

    # --- Header ---
    elements.append(Paragraph("Pay Stub", _TITLE_STYLE))
    elements.append(Spacer(1, 4))

    # --- Employer / Employee info ---
    employer_addr = _format_address(
        employer_address_line1,
        employer_address_line2,
        employer_address_city,
        employer_address_state,
        employer_address_zip,
    )
    employee_addr = _format_address(
        employee_address_line1,
        employee_address_line2,
        employee_address_city,
        employee_address_state,
        employee_address_zip,
    )

    info_data = [
        [
            Paragraph("<b>From:</b>", _NORMAL),
            Paragraph("<b>To:</b>", _NORMAL),
        ],
        [
            Paragraph(f"{employer_name}<br/>EIN: {employer_ein}<br/>{employer_addr}", _NORMAL),
            Paragraph(f"{employee_name}<br/>Hired: {employee_hire_date}<br/>{employee_addr}", _NORMAL),
        ],
    ]
    info_table = Table(info_data, colWidths=[3.5 * inch, 3.5 * inch])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(info_table)
    elements.append(Spacer(1, 10))

    # --- Period info ---
    period_data = [[
        Paragraph(f"<b>Pay Period:</b> {period_start} \u2013 {period_end}", _NORMAL),
        Paragraph(f"<b>Pay Date:</b> {pay_date}", _NORMAL),
    ]]
    period_table = Table(period_data, colWidths=[4 * inch, 3 * inch])
    elements.append(period_table)
    elements.append(Spacer(1, 10))

    # --- Hours breakdown ---
    elements.append(Paragraph("Hours Worked", _HEADER_STYLE))
    hours_header: list[object] = ["Category", "Hours"]
    hours_rows: list[list[object]] = [hours_header]
    for label, val in [
        ("Regular", regular_hours),
        ("Overtime", overtime_hours),
        ("Other Paid", other_paid_hours),
        ("Unpaid", unpaid_hours),
    ]:
        if Decimal(val) > 0:
            hours_rows.append([label, _fmt_hours(val)])
    hours_table = Table(hours_rows, colWidths=[2.5 * inch, 1.5 * inch])
    hours_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    elements.append(hours_table)
    if overtime_workweek is not None:
        elements.append(
            Paragraph(
                f"Overtime workweek: {overtime_workweek}; effective overtime rate: "
                f"{_fmt(effective_overtime_rate)}",
                _SMALL,
            )
        )
    elements.append(Spacer(1, 10))

    # --- Earnings ---
    elements.append(Paragraph("Earnings", _HEADER_STYLE))
    earnings_rows: list[list[object]] = [
        [
            Paragraph("", _NORMAL),
            Paragraph("<b>This Period</b>", _BOLD),
            Paragraph("<b>YTD</b>", _BOLD),
        ],
        [
            Paragraph("Hourly rate", _NORMAL),
            Paragraph(_fmt(hourly_rate), _NORMAL),
            Paragraph("", _NORMAL),
        ],
        [
            Paragraph("Straight-time pay", _NORMAL),
            Paragraph(_fmt(straight_time_pay), _NORMAL),
            Paragraph("", _NORMAL),
        ],
        [
            Paragraph("Overtime premium (0.5x)", _NORMAL),
            Paragraph(_fmt(overtime_premium_pay), _NORMAL),
            Paragraph("", _NORMAL),
        ],
        [
            Paragraph("<b>Gross Pay</b>", _BOLD),
            Paragraph(f"<b>{_fmt(gross)}</b>", _BOLD),
            Paragraph(f"<b>{_fmt_or_dash(gross_ytd)}</b>", _BOLD),
        ],
    ]
    earnings_table = Table(earnings_rows, colWidths=[3 * inch, 2 * inch, 2 * inch])
    earnings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, -2), (-1, -2), 1, colors.black),
    ]))
    elements.append(earnings_table)
    elements.append(Spacer(1, 10))

    # --- Deductions ---
    elements.append(Paragraph("Deductions", _HEADER_STYLE))
    w = withholding_current
    wy = withholding_ytd
    deductions_rows: list[list[object]] = [
        [
            Paragraph("", _NORMAL),
            Paragraph("<b>This Period</b>", _BOLD),
            Paragraph("<b>YTD</b>", _BOLD),
        ],
        _withholding_row("Social Security (6.2%)", w.get("social_security"), wy.get("social_security") if wy else None),
        _withholding_row("Medicare (1.45%)", w.get("medicare"), wy.get("medicare") if wy else None),
        _withholding_row("Additional Medicare (0.9%)", w.get("additional_medicare"), wy.get("additional_medicare") if wy else None),
        _withholding_row("Federal Income Tax", w.get("federal_income_tax"), wy.get("federal_income_tax") if wy else None),
        _withholding_row("WA Paid Family & Medical Leave", w.get("wa_pfml_employee"), wy.get("wa_pfml_employee") if wy else None),
        _withholding_row("WA Cares Fund", w.get("wa_cares_employee"), wy.get("wa_cares_employee") if wy else None),
        [
            Paragraph("<b>Total Deductions</b>", _BOLD),
            Paragraph(f"<b>{_fmt(total_withholding_current)}</b>", _BOLD),
            Paragraph(f"<b>{_fmt_or_dash(total_withholding_ytd)}</b>", _BOLD),
        ],
    ]
    deductions_table = Table(deductions_rows, colWidths=[3 * inch, 2 * inch, 2 * inch])
    deductions_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, -2), (-1, -2), 1, colors.black),
    ]))
    elements.append(deductions_table)
    elements.append(Spacer(1, 10))

    # --- Net Pay ---
    elements.append(Paragraph("Net Pay", _HEADER_STYLE))
    net_rows: list[list[object]] = [
        [
            Paragraph("", _NORMAL),
            Paragraph("<b>This Period</b>", _BOLD),
            Paragraph("<b>YTD</b>", _BOLD),
        ],
        [
            Paragraph("<b>Net Pay</b>", _BOLD),
            Paragraph(f"<b>{_fmt(net_pay_current)}</b>", _BOLD),
            Paragraph(f"<b>{_fmt_or_dash(net_pay_ytd)}</b>", _BOLD),
        ],
    ]
    net_table = Table(net_rows, colWidths=[3 * inch, 2 * inch, 2 * inch])
    net_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.Color(0.95, 0.95, 0.85)),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 16))

    # --- Footer ---
    elements.append(Paragraph(
        "This pay stub was generated by Pappy. "
        "Washington requires an itemized wage statement each pay period.",
        _SMALL,
    ))

    doc.build(elements)
    return buf.getvalue()
