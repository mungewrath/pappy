"""A float-rejecting `Decimal` type for rates and hour counts.

Per design-doc.md §5.5, only monetary *results* are `Money` (quantized to
the cent). Rates (tax rates, pay rates, overtime multipliers) and hour
counts stay unquantized `Decimal` at full precision, but must still never
silently accept a `float` — the whole point of the money story falls apart
if a rate arrives as an IEEE-754 approximation.

Use `StrictDecimal` as a Pydantic field annotation:

    class HourLine(BaseModel):
        hours: StrictDecimal
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema


class _StrictDecimalAnnotation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> Decimal:
            if isinstance(value, bool):
                raise TypeError("Decimal field cannot be constructed from bool")
            if isinstance(value, float):
                raise TypeError(
                    "Decimal field cannot be constructed from float; pass a str, int, or Decimal"
                )
            if isinstance(value, Decimal):
                return value
            if isinstance(value, (str, int)):
                try:
                    return Decimal(value)
                except InvalidOperation as exc:
                    raise ValueError(f"Not a valid decimal: {value!r}") from exc
            raise TypeError(f"Cannot build Decimal from {type(value).__name__}")

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, return_schema=core_schema.str_schema()
            ),
        )


StrictDecimal = Annotated[Decimal, _StrictDecimalAnnotation]
