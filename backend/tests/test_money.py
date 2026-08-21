from decimal import Decimal

import pytest

from pappy.money import Money


def test_construct_from_str_int_decimal() -> None:
    assert Money("12.50").amount == Decimal("12.50")
    assert Money(5).amount == Decimal("5.00")
    assert Money(Decimal("3.005")).amount == Decimal("3.01")  # half-up


def test_rejects_float() -> None:
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]


def test_rejects_bool() -> None:
    with pytest.raises(TypeError):
        Money(True)


def test_arithmetic() -> None:
    assert Money("10.00") + Money("5.25") == Money("15.25")
    assert Money("10.00") - Money("5.25") == Money("4.75")
    assert Money("10.00") * Decimal("1.5") == Money("15.00")


def test_multiply_rejects_float() -> None:
    with pytest.raises(TypeError):
        Money("10.00") * 1.5  # type: ignore[operator]


def test_ordering_and_equality() -> None:
    assert Money("1.00") < Money("2.00")
    assert Money("2.00") > Money("1.00")
    assert Money("1.00") <= Money("1.00")
    assert Money("1.00") == Money("1.00")
    assert Money("1.00") != Money("2.00")


def test_sum() -> None:
    assert Money.sum([Money("1.11"), Money("2.22"), Money("3.33")]) == Money("6.66")


def test_str_and_repr() -> None:
    assert str(Money("1.5")) == "1.50"
    assert repr(Money("1.5")) == "Money('1.50')"


def test_pydantic_round_trip() -> None:
    from pydantic import BaseModel

    class Wrapper(BaseModel):
        amount: Money

    w = Wrapper(amount=Money("42.00"))
    assert w.model_dump(mode="json") == {"amount": "42.00"}

    w2 = Wrapper.model_validate({"amount": "42.00"})
    assert w2.amount == Money("42.00")

    with pytest.raises(TypeError):
        Wrapper.model_validate({"amount": 42.0})
