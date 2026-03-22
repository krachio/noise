from __future__ import annotations

from krach.patterns.ir import Degrade, Fast, Rev
from krach.patterns.pattern import note
from krach.patterns.transform import reverse, fast, thin


class TestTransformApplication:
    def test_fast_matches_method(self) -> None:
        p = note(60)
        assert fast(2)(p).node == p.fast(2).node

    def test_reverse_matches_method(self) -> None:
        p = note(60)
        assert reverse(p).node == p.reverse().node

    def test_thin_matches_method(self) -> None:
        p = note(60)
        assert thin(0.3)(p).node == p.thin(0.3).node


class TestTransformComposition:
    def test_rshift_composes(self) -> None:
        p = note(60)
        fx = fast(2) >> thin(0.1)
        result = fx(p)
        expected = p.fast(2).thin(0.1)
        assert result.node == expected.node

    def test_triple_compose(self) -> None:
        p = note(60)
        fx = fast(2) >> reverse >> thin(0.1)
        result = fx(p)
        assert isinstance(result.node, Degrade)
        assert isinstance(result.node.child, Rev)
        inner = result.node.child
        assert isinstance(inner, Rev)
        assert isinstance(inner.child, Fast)


class TestTransformImmutability:
    def test_compose_returns_new(self) -> None:
        a = fast(2)
        b = thin(0.1)
        c = a >> b
        p = note(60)
        assert a(p).node != c(p).node
