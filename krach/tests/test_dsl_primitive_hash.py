"""Tests for Primitive.__eq__ and __hash__ — structural, not identity-based."""

from krach.ir.signal import Primitive


def test_same_name_equal() -> None:
    """Two Primitives with the same name and stateful flag are equal."""
    a = Primitive("add")
    b = Primitive("add")
    assert a == b


def test_same_name_same_hash() -> None:
    """Equal primitives have the same hash."""
    a = Primitive("add")
    b = Primitive("add")
    assert hash(a) == hash(b)


def test_different_name_not_equal() -> None:
    a = Primitive("add")
    b = Primitive("mul")
    assert a != b


def test_stateful_differs() -> None:
    """Primitives with same name but different stateful flag are not equal."""
    a = Primitive("delay", stateful=False)
    b = Primitive("delay", stateful=True)
    assert a != b
    assert hash(a) != hash(b)


def test_usable_as_dict_key() -> None:
    """Primitives can be used as dictionary keys based on (name, stateful)."""
    a = Primitive("sin")
    b = Primitive("sin")
    d: dict[Primitive, str] = {a: "first"}
    assert d[b] == "first"  # b looks up a's entry because they're equal


def test_usable_in_set() -> None:
    """Equal primitives deduplicate in a set."""
    a = Primitive("cos")
    b = Primitive("cos")
    s = {a, b}
    assert len(s) == 1


def test_singleton_still_equal() -> None:
    """The existing singletons (add_p, etc.) remain equal to themselves."""
    from krach.signal.primitives import add_p, mul_p
    assert add_p == add_p
    assert add_p != mul_p
    assert hash(add_p) == hash(add_p)
