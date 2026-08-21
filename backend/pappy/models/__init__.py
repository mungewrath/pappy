"""Pydantic domain models (design-doc.md §3).

Intentionally not a barrel module that re-exports every entity: `payrun`
depends on `pappy.calc.gross`, which itself depends on `pappy.models.common`
for `HourCategory`/`OvertimePolicy`. Eagerly importing `payrun` here would
make importing *any* model (even `Employer`) risk a circular import with
`pappy.calc.gross`, depending on which module happens to be imported first.
Import what you need directly, e.g. `from pappy.models.payrun import PayRun`.
"""

from __future__ import annotations
