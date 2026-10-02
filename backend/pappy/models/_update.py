"""Reading explicitly-set fields off an update model.

`Model.apply_update` merges a partial update into a stored entity, and the
obvious `data.model_dump(exclude_unset=True)` is wrong for any field with a
custom serializer. Pydantic's `plain_serializer_function_ser_schema` (which
`Money` uses to emit a decimal string) fires in *every* dump mode, including
python mode — so the dump hands back `str` where the entity expects `Money`.
`model_copy` does not validate, so the entity ends up holding a bare string
and raises `AttributeError` the next time anything serializes it.

`StrictDecimal` fields never hit this: a plain `Decimal` has no python-mode
serializer, which is why the bug lay dormant until a `Money` field appeared.

Reading the validated attributes instead keeps the real objects. `model_fields_set`
is exactly the set of fields the client actually sent, so it matches
`exclude_unset=True` semantics.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def _set_fields(data: BaseModel) -> dict[str, Any]:
    """The explicitly-supplied fields of `data`, with their validated values."""
    return {name: getattr(data, name) for name in data.model_fields_set}
