"""Single-table key construction (design-doc.md §4).

    | Entity   | PK                  | SK                              |
    |----------|---------------------|---------------------------------|
    | Employer | EMPLOYER#<id>       | PROFILE                         |
    | Employee | EMPLOYER#<id>       | EMPLOYEE#<empId>                |
    | PayRun   | EMPLOYER#<id>       | PAYRUN#<payDate>#<runId>        |

Sort keys are date-prefixed and zero-padded ISO (`date.isoformat()` already
sorts correctly), so "all pay runs in 2026" is a single `Query` with a
`begins_with` condition, and no GSI is needed at this scale.
"""

from __future__ import annotations

from datetime import date


def employer_pk(employer_id: str) -> str:
    return f"EMPLOYER#{employer_id}"


def employer_profile_sk() -> str:
    return "PROFILE"


def employee_sk(employee_id: str) -> str:
    return f"EMPLOYEE#{employee_id}"


def employee_sk_prefix() -> str:
    return "EMPLOYEE#"


def payrun_sk(pay_date: date, run_id: str) -> str:
    return f"PAYRUN#{pay_date.isoformat()}#{run_id}"


def payrun_sk_prefix(year: int | None = None) -> str:
    if year is None:
        return "PAYRUN#"
    return f"PAYRUN#{year:04d}-"
