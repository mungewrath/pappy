"""EFW2 wage-file builder for SSA Business Services Online (§6.5).

Builds the fixed-width electronic file that uploads W-2 Copy A data to
SSA's BSO portal. Per §6.5 the app never prints Copy A on paper — this
file *is* the Copy A filing path, and it stays a pure-text artifact until
the document store arrives.

**Verify before filing.** Like every statutory value in Pappy (§5.2), the
field layout below is treated as data subject to annual verification: SSA
publishes the current EFW2 specifications each fall
(ssa.gov/employer/efw/2_efw2specs.htm). The layout lives in one place per
record (`_RW_FIELDS` / `_RE_FIELDS`) so a spec correction is a table edit,
not code surgery. Amounts are integer cents, right-aligned, zero-filled;
text is upper-case, left-aligned, space-filled; every record is exactly
512 characters.

An employer-prepared file omits the RA transmitter record (that belongs to
payroll agents); the file here is therefore RE + RW records only. RS state
records do not apply to Washington — there is no state income tax
withholding to report.
"""

from __future__ import annotations

from dataclasses import dataclass

from pappy.money import Money

RECORD_LENGTH = 512


class Efw2Error(ValueError):
    """A value cannot be placed into the fixed-width record."""


@dataclass(frozen=True)
class Efw2WageRecord:
    """One employee's RW record inputs.

    `ssn` is supplied transiently at generation time and never persisted
    (design-doc.md §7.3); a blank SSN produces a structurally valid record
    that BSO will reject — useful for previews, never for filing.
    """

    first_name: str
    middle_initial: str
    last_name: str
    ssn: str | None
    wages: Money
    fit_withheld: Money
    ss_wages: Money
    ss_tax_withheld: Money
    medicare_wages: Money
    medicare_tax_withheld: Money


# (field name, width). Concatenating the values in order must produce
# exactly RECORD_LENGTH characters — asserted at build time, so a future
# spec edit that breaks the arithmetic fails loudly instead of silently
# shifting every downstream byte. A width of 0 means "pad to the end".
_RW_FIELDS: tuple[tuple[str, int], ...] = (
    ("record_id", 2),  # "RW"
    ("tax_year", 4),
    ("ein", 9),
    ("ssn", 9),
    ("first_name", 21),
    ("middle_initial", 16),
    ("last_name", 21),
    ("suffix", 6),
    ("location_address", 40),
    ("delivery_address", 40),
    ("city", 30),
    ("state", 2),
    ("zip_code", 9),
    ("blank", 10),
    ("wages", 12),
    ("fit_withheld", 12),
    ("ss_wages", 12),
    ("ss_tax_withheld", 12),
    ("medicare_wages", 12),
    ("medicare_tax_withheld", 12),
    ("tail", 0),  # unused tail fields, spaces
)

_RE_FIELDS: tuple[tuple[str, int], ...] = (
    ("record_id", 2),  # "RE"
    ("tax_year", 4),
    ("ein", 9),
    ("employer_name", 57),
    ("location_address", 40),
    ("delivery_address", 40),
    ("city", 30),
    ("state", 2),
    ("zip_code", 9),
    ("blank", 10),
    ("kind_of_employer", 1),  # blank for a straightforward household employer
    ("kind_of_payer", 1),  # "H" — household employer
    ("tail", 0),
)

_TEXT_ALLOWED = set(" ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&'()*+,-./:;@")


def _sanitize_text(value: str, *, width: int, label: str) -> str:
    cleaned = "".join(ch if ch in _TEXT_ALLOWED else " " for ch in value.upper())
    cleaned = " ".join(cleaned.split())  # collapse runs of blanks
    if len(cleaned) > width:
        raise Efw2Error(f"{label} does not fit {width} characters: {value!r}")
    return cleaned.ljust(width)


def _amount(value: Money, *, label: str) -> str:
    cents = int((value.amount * 100).to_integral_value())
    if cents < 0 or cents > 999_999_999_999:  # 12 digits
        raise Efw2Error(f"{label} out of range for EFW2: {value}")
    return f"{cents:012d}"


def _digits_or_blank(value: str | None, *, width: int, label: str) -> str:
    if value is None or value.strip() == "":
        return " " * width
    digits = value.replace("-", "").replace(" ", "")
    if not digits.isdigit() or len(digits) != width:
        raise Efw2Error(f"{label} must be exactly {width} digits: {value!r}")
    return digits


def _build_record(
    fields: tuple[tuple[str, int], ...], values: dict[str, object], label: str
) -> str:
    record = ""
    for name, width in fields:
        raw = values[name]
        if width == 0 or name in ("tail",):
            remaining = RECORD_LENGTH - len(record)
            if remaining < 0:
                raise Efw2Error(f"{label} record exceeds {RECORD_LENGTH} characters")
            record += " " * remaining
            continue
        if raw is None or name.startswith("blank"):
            record += " " * width
        elif name == "ssn":  # digits-only field, dashes tolerated on input
            record += _digits_or_blank(str(raw), width=width, label=f"{label}.{name}")
        elif isinstance(raw, Money):
            record += _amount(raw, label=f"{label}.{name}")
        elif isinstance(raw, int):
            record += str(raw)
        else:
            record += _sanitize_text(str(raw), width=width, label=f"{label}.{name}")
    if len(record) != RECORD_LENGTH:
        raise Efw2Error(
            f"{label} record is {len(record)} characters, must be {RECORD_LENGTH}"
        )
    return record


def _rw_record(wage: Efw2WageRecord, *, tax_year: int, ein: str) -> str:
    return _build_record(
        _RW_FIELDS,
        {
            "record_id": "RW",
            "tax_year": tax_year,
            "ein": ein,
            "ssn": wage.ssn,
            "first_name": wage.first_name,
            "middle_initial": wage.middle_initial,
            "last_name": wage.last_name,
            "suffix": None,
            "location_address": None,
            "delivery_address": None,
            "city": None,
            "state": None,
            "zip_code": None,
            "blank": None,
            "wages": wage.wages,
            "fit_withheld": wage.fit_withheld,
            "ss_wages": wage.ss_wages,
            "ss_tax_withheld": wage.ss_tax_withheld,
            "medicare_wages": wage.medicare_wages,
            "medicare_tax_withheld": wage.medicare_tax_withheld,
            "tail": None,
        },
        label="RW",
    )


def _re_record(
    *,
    tax_year: int,
    ein: str,
    employer_name: str,
    city: str,
    state: str,
    zip_code: str,
) -> str:
    return _build_record(
        _RE_FIELDS,
        {
            "record_id": "RE",
            "tax_year": tax_year,
            "ein": ein,
            "employer_name": employer_name,
            "location_address": None,
            "delivery_address": None,
            "city": city,
            "state": state,
            "zip_code": zip_code,
            "blank": None,
            "kind_of_employer": None,
            "kind_of_payer": "H",
            "tail": None,
        },
        label="RE",
    )


def split_full_name(full_name: str) -> tuple[str, str, str]:
    """Naive first/middle/last split for the RW name fields.

    Household payroll stores one display name; the file wants parts. The
    first token is the given name, the last is the surname, anything
    between becomes the middle-initial slot truncated to fit.
    """
    tokens = [token for token in full_name.split() if token]
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""
    first = tokens[0]
    last = tokens[-1]
    middle = " ".join(tokens[1:-1])
    return first, middle[:16], last


def build_efw2(
    *,
    tax_year: int,
    ein: str,
    employer_name: str,
    city: str,
    state: str,
    zip_code: str,
    wage_records: list[Efw2WageRecord],
) -> str:
    """The complete file: one RE record followed by one RW per employee."""
    if not wage_records:
        raise Efw2Error("an EFW2 file needs at least one wage record")
    clean_ein = _digits_or_blank(ein, width=9, label="EIN")
    lines = [
        _re_record(
            tax_year=tax_year,
            ein=clean_ein,
            employer_name=employer_name,
            city=city,
            state=state,
            zip_code=zip_code,
        )
    ]
    for wage in sorted(wage_records, key=lambda w: (w.last_name.upper(), w.first_name.upper())):
        lines.append(_rw_record(wage, tax_year=tax_year, ein=clean_ein))
    # Spec: each record terminated by CR+LF.
    return "\r\n".join(lines) + "\r\n"
