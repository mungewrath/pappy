"""Decimal-backed money primitive.

See design-doc.md §5.5. Highlights:

- A single explicit `decimal` context is installed at import time
  (`ROUND_HALF_UP`, ample precision, traps on `InvalidOperation` and
  `DivisionByZero`) so a bad computation raises instead of silently
  producing `NaN`/`Infinity`.
- `Money` wraps a `Decimal` quantized to the cent with `ROUND_HALF_UP`. It
  can only be constructed from `str`, `int`, or `Decimal` — never `float` —
  so "someone passed a float in" is a `TypeError` at the call site, not a
  rounding bug discovered a year later.
- Rates and hour counts are *not* `Money` — they stay unquantized
  `Decimal`. Only monetary results are quantized, and only once per line.
"""

from __future__ import annotations

import decimal
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

# One explicit context, installed once at import time. `Decimal()` itself
# never rounds on construction, but arithmetic (add/mul/quantize) is
# performed under this context, so precision/traps apply everywhere.
decimal.getcontext().prec = 40
decimal.getcontext().rounding = decimal.ROUND_HALF_UP
decimal.getcontext().traps[decimal.InvalidOperation] = True
decimal.getcontext().traps[decimal.DivisionByZero] = True

_CENT = Decimal("0.01")


class Money:
    """An exact, cent-quantized amount of US dollars.

    Construct from `str`, `int`, or `Decimal` only:

        Money("12.50")
        Money(0)
        Money(Decimal("3.005"))  # quantizes to 3.01 (half-up)

    `float` is rejected outright — floats cannot represent most decimal
    cent values exactly, and silently accepting one is exactly the bug
    class this type exists to prevent.
    """

    __slots__ = ("_amount",)

    zero: ClassVar[Money]

    def __init__(self, value: str | int | Decimal) -> None:
        if isinstance(value, bool):  # bool is an int subclass; reject explicitly
            raise TypeError("Money cannot be constructed from bool")
        if isinstance(value, float):
            raise TypeError("Money cannot be constructed from float; pass a str, int, or Decimal")
        if not isinstance(value, (str, int, Decimal)):
            raise TypeError(
                f"Money cannot be constructed from {type(value).__name__}; "
                "pass a str, int, or Decimal"
            )
        try:
            amount = Decimal(value)
        except decimal.InvalidOperation as exc:
            raise ValueError(f"Not a valid decimal amount: {value!r}") from exc
        self._amount = amount.quantize(_CENT, rounding=decimal.ROUND_HALF_UP)

    @property
    def amount(self) -> Decimal:
        """The underlying cent-quantized Decimal."""
        return self._amount

    def __add__(self, other: Money) -> Money:
        self._check_type(other)
        return Money(self._amount + other._amount)

    def __sub__(self, other: Money) -> Money:
        self._check_type(other)
        return Money(self._amount - other._amount)

    def __neg__(self) -> Money:
        return Money(-self._amount)

    def __mul__(self, rate: Decimal) -> Money:
        """Multiply by an unquantized rate (e.g. a tax rate or hour count).

        The result is quantized once, here — this is the one place a
        `Money` is allowed to be produced from a non-Money operand.
        """
        if isinstance(rate, float):
            raise TypeError("Money cannot be multiplied by a float; use Decimal")
        if not isinstance(rate, Decimal):
            raise TypeError(f"Money cannot be multiplied by {type(rate).__name__}")
        return Money(self._amount * rate)

    __rmul__ = __mul__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._amount == other._amount

    def __lt__(self, other: Money) -> bool:
        self._check_type(other)
        return self._amount < other._amount

    def __le__(self, other: Money) -> bool:
        self._check_type(other)
        return self._amount <= other._amount

    def __gt__(self, other: Money) -> bool:
        self._check_type(other)
        return self._amount > other._amount

    def __ge__(self, other: Money) -> bool:
        self._check_type(other)
        return self._amount >= other._amount

    def __hash__(self) -> int:
        return hash(self._amount)

    def __repr__(self) -> str:
        return f"Money('{self._amount}')"

    def __str__(self) -> str:
        return str(self._amount)

    @staticmethod
    def _check_type(other: object) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Expected Money, got {type(other).__name__}")

    @classmethod
    def sum(cls, amounts: list[Money]) -> Money:
        total = cls.zero
        for amount in amounts:
            total = total + amount
        return total

    # --- Pydantic integration -------------------------------------------------
    #
    # Serializes to/from a plain decimal string, so DynamoDB and JSON both see
    # e.g. "1234.56" rather than a float approximation. `boto3`'s DynamoDB
    # serializer round-trips `Decimal` directly, so the repo layer converts
    # this string to `Decimal` at the storage boundary (see pappy/repo).

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> Money:
            if isinstance(value, Money):
                return value
            if isinstance(value, (str, int, Decimal)) and not isinstance(value, bool):
                return cls(value)
            raise TypeError(f"Cannot build Money from {type(value).__name__}")

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda m: str(m.amount), return_schema=core_schema.str_schema()
            ),
        )


Money.zero = Money(0)
