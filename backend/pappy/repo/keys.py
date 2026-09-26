"""Single-table key construction (design-doc.md §4).

    | Entity   | PK                  | SK                                    |
    |----------|---------------------|---------------------------------------|
    | Employer | EMPLOYER#<id>       | PROFILE                               |
    | Employee | EMPLOYER#<id>       | EMPLOYEE#<empId>                      |
    | W-4 election | EMPLOYER#<id>   | EMPLOYEE#<empId>#W4#<effectiveDate>   |
    | PayRun   | EMPLOYER#<id>       | PAYRUN#<payDate>#<runId>              |
    | YTD accumulator | EMPLOYER#<id> | YTD#<taxYear>#<empId>                |
    | Reminder | EMPLOYER#<id>       | REMINDER#<dueDate>#<ruleId>           |
    | Document | EMPLOYER#<id>       | DOC#<taxYear>#<type>#<docId>          |
    | RateTable | RATES#<taxYear>    | VERSION#<n>                           |

Sort keys are date-prefixed and zero-padded ISO (`date.isoformat()` already
sorts correctly), so "all pay runs in 2026" is a single `Query` with a
`begins_with` condition, and no GSI is needed at this scale.

Note the W-4 SK nests under the employee's SK prefix, so an employee's
elections are one `Query` — but `EMPLOYEE#` alone no longer matches only
employee items; `employee_repo.list_for_employer` filters the nested
elections out.
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


def w4_sk(employee_id: str, effective_date: date) -> str:
    return f"{employee_sk(employee_id)}#W4#{effective_date.isoformat()}"


def w4_sk_prefix(employee_id: str) -> str:
    return f"{employee_sk(employee_id)}#W4#"


def payrun_sk(pay_date: date, run_id: str) -> str:
    return f"PAYRUN#{pay_date.isoformat()}#{run_id}"


def payrun_sk_prefix(year: int | None = None) -> str:
    if year is None:
        return "PAYRUN#"
    return f"PAYRUN#{year:04d}-"


def ytd_sk(tax_year: int, employee_id: str) -> str:
    return f"YTD#{tax_year:04d}#{employee_id}"


def reminder_sk(due_date: date, rule_id: str) -> str:
    return f"REMINDER#{due_date.isoformat()}#{rule_id}"


def reminder_sk_prefix() -> str:
    return "REMINDER#"


def reminder_sk_prefix_up_to(due_before: date) -> str:
    """Sort-key range for "reminders due before X" (§4): ISO dates sort
    lexicographically, so everything strictly before `due_before` shares one
    `begins_with`-compatible prefix scan bounded by a range condition."""
    return f"REMINDER#{due_before.isoformat()}"


def doc_sk(tax_year: int, doc_type: str, doc_id: str) -> str:
    return f"DOC#{tax_year:04d}#{doc_type}#{doc_id}"


def doc_sk_prefix(tax_year: int | None = None, doc_type: str | None = None) -> str:
    parts = ["DOC#"]
    if tax_year is not None:
        parts.append(f"{tax_year:04d}#")
        if doc_type is not None:
            parts.append(f"{doc_type}#")
    return "".join(parts)


def doc_run_index_sk(tax_year: int, run_id: str, doc_id: str) -> str:
    return f"DOCIDX#{tax_year:04d}#{run_id}#{doc_id}"


def doc_run_index_prefix() -> str:
    return "DOCIDX#"


def rates_pk(tax_year: int) -> str:
    return f"RATES#{tax_year:04d}"


def rates_version_sk(version: int) -> str:
    return f"VERSION#{version:04d}"
