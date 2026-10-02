"""Dependent care FSA receipt PDF generator (design-doc.md §6.3).

A DCFSA reimbursement receipt has to carry the provider's name, address and
TIN, the dates of service, the amount paid, and the dependent's name — and it
has to be *signed by the provider* to be worth anything to a plan
administrator. This renders that artifact with `reportlab`.

Like `pay_stub`, the generator takes flat string arguments and does no I/O or
model lookups, which keeps it trivially testable in isolation: the service
resolves the ledger figures and hands over strings.

The provider TIN is passed in per generation and is never stored — it is not
an SSN, but it is the same class of identifier, and §7.3's rule is that
identifying numbers reach a document once and are not written down anywhere
else. The signature block is left unsigned on purpose: this app cannot sign
for a human, and a receipt that looked machine-signed would be worse than one
that visibly awaits a signature.
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
    "FsaTitle",
    parent=_STYLES["Title"],
    fontSize=16,
    spaceAfter=4,
)
_SUBTITLE_STYLE = ParagraphStyle(
    "FsaSubtitle",
    parent=_STYLES["Normal"],
    fontSize=9,
    textColor=colors.grey,
    spaceAfter=10,
)
_HEADER_STYLE = ParagraphStyle(
    "FsaHeader",
    parent=_STYLES["Heading2"],
    fontSize=11,
    spaceAfter=4,
    spaceBefore=10,
)
_NORMAL = _STYLES["Normal"]
_SMALL = ParagraphStyle(
    "FsaSmall",
    parent=_NORMAL,
    fontSize=8,
    textColor=colors.grey,
)
_BOLD = ParagraphStyle(
    "FsaBold",
    parent=_NORMAL,
    fontName="Helvetica-Bold",
)


def _fmt(value: str) -> str:
    return f"${Decimal(value):,.2f}"


def _format_address(line1: str, line2: str | None, city: str, state: str, zip_code: str) -> str:
    lines = [line1]
    if line2:
        lines.append(line2)
    lines.append(f"{city}, {state} {zip_code}")
    return "<br/>".join(lines)


def generate_fsa_receipt_pdf(
    *,
    employer_name: str,
    employer_address_line1: str,
    employer_address_city: str,
    employer_address_state: str,
    employer_address_zip: str,
    provider_name: str,
    provider_tin: str,
    provider_address_line1: str,
    provider_address_city: str,
    provider_address_state: str,
    provider_address_zip: str,
    dependent_name: str,
    service_start: str,
    service_end: str,
    amount_paid: str,
    wage_basis_note: str,
    employer_address_line2: str | None = None,
    provider_address_line2: str | None = None,
    tax_year: int | None = None,
) -> bytes:
    """Generate a dependent care FSA receipt PDF and return the raw bytes.

    All data is passed in — this function does no database or S3 I/O.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
    )

    elements: list[Flowable] = []

    elements.append(Paragraph("Dependent Care FSA Receipt", _TITLE_STYLE))
    elements.append(
        Paragraph(
            "For reimbursement under a Dependent Care Flexible Spending Account",
            _SUBTITLE_STYLE,
        )
    )

    # --- Claimant / employer ---
    elements.append(Paragraph("Claim submitted by", _HEADER_STYLE))
    employer_addr = _format_address(
        employer_address_line1,
        employer_address_line2,
        employer_address_city,
        employer_address_state,
        employer_address_zip,
    )
    claimant = Table(
        [[Paragraph(f"<b>{employer_name}</b><br/>{employer_addr}", _NORMAL)]],
        colWidths=[6.5 * inch],
    )
    claimant.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(claimant)
    elements.append(Spacer(1, 8))

    # --- Provider (the care provider who signs) ---
    elements.append(Paragraph("Care provider", _HEADER_STYLE))
    provider_addr = _format_address(
        provider_address_line1,
        provider_address_line2,
        provider_address_city,
        provider_address_state,
        provider_address_zip,
    )
    provider = Table(
        [
            [
                Paragraph("<b>Name</b>", _NORMAL),
                Paragraph(provider_name, _NORMAL),
            ],
            [
                Paragraph("<b>Address</b>", _NORMAL),
                Paragraph(provider_addr, _NORMAL),
            ],
            [
                Paragraph("<b>TIN / SSN</b>", _NORMAL),
                Paragraph(provider_tin, _NORMAL),
            ],
        ],
        colWidths=[1.4 * inch, 5.1 * inch],
    )
    provider.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.95, 0.95, 0.95)),
            ]
        )
    )
    elements.append(provider)
    elements.append(Spacer(1, 10))

    # --- Dependent and service period ---
    elements.append(Paragraph("Dependent and services", _HEADER_STYLE))
    dependent_rows: list[list[object]] = [
        [
            Paragraph("<b>Dependent's name</b>", _NORMAL),
            Paragraph(dependent_name, _NORMAL),
        ],
        [
            Paragraph("<b>Dates of service</b>", _NORMAL),
            Paragraph(f"{service_start} – {service_end}", _NORMAL),
        ],
    ]
    if tax_year is not None:
        dependent_rows.append(
            [Paragraph("<b>Tax year</b>", _NORMAL), Paragraph(str(tax_year), _NORMAL)]
        )
    dependent = Table(dependent_rows, colWidths=[1.6 * inch, 4.9 * inch])
    dependent.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
            ]
        )
    )
    elements.append(dependent)
    elements.append(Spacer(1, 10))

    # --- Amount ---
    elements.append(Paragraph("Amount paid", _HEADER_STYLE))
    amount = Table(
        [
            [
                Paragraph("<b>Total amount paid for the above services</b>", _BOLD),
                Paragraph(f"<b>{_fmt(amount_paid)}</b>", _BOLD),
            ]
        ],
        colWidths=[4.5 * inch, 2.0 * inch],
    )
    amount.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.Color(0.95, 0.95, 0.85)),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(amount)
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(wage_basis_note, _SMALL))
    elements.append(Spacer(1, 16))

    # --- Statement of services ---
    elements.append(Paragraph("Statement of services", _HEADER_STYLE))
    elements.append(
        Paragraph(
            "I provided dependent care services in my capacity as the care "
            "provider named above for the dependent named above, during the "
            "dates of service shown. I certify that the amount stated is the "
            "full amount paid for those services, that the services were "
            "provided in my home, and that I have not been reimbursed for "
            "them from any other source.",
            _NORMAL,
        )
    )
    elements.append(Spacer(1, 22))

    # --- Signature block ---
    # Rule lengths are sized to their columns — a longer rule wraps onto a
    # second line and reads as a stray fragment rather than a signature line.
    signature = Table(
        [
            [
                Paragraph("_________________________________", _NORMAL),
                Paragraph("__________________", _NORMAL),
            ],
            [
                Paragraph("Signature of care provider", _SMALL),
                Paragraph("Date", _SMALL),
            ],
        ],
        colWidths=[4.3 * inch, 2.2 * inch],
    )
    signature.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(signature)
    elements.append(Spacer(1, 16))

    elements.append(
        Paragraph(
            "This receipt must be signed by the care provider to be valid. "
            "Generated by Pappy from finalized pay runs; the signature is "
            "deliberately left blank.",
            _SMALL,
        )
    )

    doc.build(elements)
    return buf.getvalue()
