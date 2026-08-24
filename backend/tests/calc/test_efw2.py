"""EFW2 fixed-width file builder (design-doc.md §6.5).

Structural assertions: exact 512-character records, zero-filled 12-digit
amounts, uppercase text fields, RE-then-RW ordering, and loud failures on
values that cannot fit. Field offsets themselves are documented as
verify-before-filing data (see pappy/calc/efw2.py).
"""

import pytest

from pappy.calc.efw2 import (
    RECORD_LENGTH,
    Efw2Error,
    Efw2WageRecord,
    build_efw2,
    split_full_name,
)
from pappy.money import Money


def _wage_record(**overrides: object) -> Efw2WageRecord:
    values: dict[str, object] = {
        "first_name": "Nanny",
        "middle_initial": "Q",
        "last_name": "Smith",
        "ssn": "123456789",
        "wages": Money("1187.50"),
        "fit_withheld": Money("100.58"),
        "ss_wages": Money("1187.50"),
        "ss_tax_withheld": Money("73.63"),
        "medicare_wages": Money("1187.50"),
        "medicare_tax_withheld": Money("17.22"),
    }
    values.update(overrides)
    return Efw2WageRecord(**values)  # type: ignore[arg-type]


@pytest.fixture
def efw2_text() -> str:
    return build_efw2(
        tax_year=2026,
        ein="12-3456789",
        employer_name="Jane Doe",
        city="Seattle",
        state="WA",
        zip_code="98101",
        wage_records=[_wage_record()],
    )


def _records(text: str) -> list[str]:
    return text.rstrip("\r\n").split("\r\n")


def test_records_are_exactly_512_characters(efw2_text: str) -> None:
    lines = _records(efw2_text)
    assert len(lines) == 2
    assert all(len(line) == RECORD_LENGTH for line in lines)


def test_re_record_header_and_household_payer_code(efw2_text: str) -> None:
    re_record = _records(efw2_text)[0]
    assert re_record.startswith("RE")
    assert re_record[2:6] == "2026"
    assert re_record[6:15] == "123456789"
    assert re_record[204:205] == "H"  # kind of payer = household employer


def test_rw_record_fields(efw2_text: str) -> None:
    rw_record = _records(efw2_text)[1]
    assert rw_record.startswith("RW")
    assert rw_record[2:6] == "2026"
    assert rw_record[6:15] == "123456789"  # EIN
    assert rw_record[15:24] == "123456789"  # SSN
    assert rw_record[24:29] == "NANNY"
    # amounts: integer cents, right-aligned, zero-filled, 12 wide
    assert rw_record[219:231] == "000000118750"  # wages $1,187.50
    assert rw_record[231:243] == "000000010058"  # FIT $100.58


def test_amount_encoding_is_integer_cents() -> None:
    record = Efw2WageRecord(
        first_name="A",
        middle_initial="",
        last_name="B",
        ssn=None,
        wages=Money("0.05"),
        fit_withheld=Money(0),
        ss_wages=Money("0.01"),
        ss_tax_withheld=Money(0),
        medicare_wages=Money("0.01"),
        medicare_tax_withheld=Money(0),
    )
    text = build_efw2(
        tax_year=2026,
        ein="123456789",
        employer_name="E",
        city="C",
        state="WA",
        zip_code="98101",
        wage_records=[record],
    )
    rw = _records(text)[1]
    assert rw[219:231].endswith("5") and rw[219:231] == "000000000005"  # $0.05
    assert rw[231:243] == "000000000000"  # zero FIT


def test_blank_ssn_produces_a_preview_record() -> None:
    text = build_efw2(
        tax_year=2026,
        ein="123456789",
        employer_name="E",
        city="C",
        state="WA",
        zip_code="98101",
        wage_records=[_wage_record(ssn=None)],
    )
    rw = _records(text)[1]
    assert rw[15:24] == "         "


def test_invalid_ein_fails_loudly() -> None:
    with pytest.raises(Efw2Error):
        build_efw2(
            tax_year=2026,
            ein="12-345",
            employer_name="E",
            city="C",
            state="WA",
            zip_code="98101",
            wage_records=[_wage_record()],
        )


def test_empty_file_refused() -> None:
    with pytest.raises(Efw2Error):
        build_efw2(
            tax_year=2026,
            ein="123456789",
            employer_name="E",
            city="C",
            state="WA",
            zip_code="98101",
            wage_records=[],
        )


def test_split_full_name() -> None:
    assert split_full_name("Nanny Q Smith") == ("Nanny", "Q", "Smith")
    assert split_full_name("Cher") == ("Cher", "", "")
    assert split_full_name("") == ("", "", "")
