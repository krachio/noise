"""Tests for path resolution — the single source of truth for path disambiguation.

Every user-facing string in krach is one of:
- NodePath: exact node name (may contain "/")
- ControlPath: node/param → engine label
- GroupPath: prefix matching multiple nodes
- UnknownPath: no match
"""

from krach._types import Node, NodePath, ControlPath, GroupPath, UnknownPath, resolve_path


def _nodes(*names: str) -> dict[str, Node]:
    """Shorthand: create a dict of minimal nodes by name."""
    return {
        n: Node(type_id=f"faust:{n}", gain=0.5, controls=("freq", "gate"))
        for n in names
    }


# ── Exact node match ─────────────────────────────────────────────────────


def test_exact_node_name() -> None:
    nodes = _nodes("bass")
    result = resolve_path("bass", nodes)
    assert result == NodePath("bass")


def test_slashed_node_name_takes_priority() -> None:
    """A node named 'drums/kick' is a NodePath, not a ControlPath."""
    nodes = _nodes("drums/kick")
    result = resolve_path("drums/kick", nodes)
    assert result == NodePath("drums/kick")


def test_slashed_node_over_control_when_both_exist() -> None:
    """If both 'drums/kick' (node) and 'drums' (node) exist,
    'drums/kick' resolves to the exact node, not drums+kick control."""
    nodes = _nodes("drums", "drums/kick")
    result = resolve_path("drums/kick", nodes)
    assert result == NodePath("drums/kick")


# ── Control path ─────────────────────────────────────────────────────────


def test_control_path() -> None:
    """'bass/cutoff' where 'bass' is a node → ControlPath."""
    nodes = _nodes("bass")
    result = resolve_path("bass/cutoff", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "bass"
    assert result.param == "cutoff"
    assert result.label == "bass/cutoff"


def test_control_path_gain() -> None:
    """'bass/gain' resolves as a control path."""
    nodes = _nodes("bass")
    result = resolve_path("bass/gain", nodes)
    assert isinstance(result, ControlPath)
    assert result.param == "gain"
    assert result.label == "bass/gain"


def test_send_suffix_rewrite() -> None:
    """'bass/verb_send' rewrites to engine label 'bass_send_verb/gain'."""
    nodes = _nodes("bass")
    result = resolve_path("bass/verb_send", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "bass"
    assert result.param == "verb_send"
    assert result.label == "bass_send_verb/gain"


def test_control_path_on_slashed_node() -> None:
    """'drums/kick/gate' where 'drums/kick' is a node → ControlPath for gate."""
    nodes = _nodes("drums/kick")
    result = resolve_path("drums/kick/gate", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "drums/kick"
    assert result.param == "gate"
    assert result.label == "drums/kick/gate"


# ── Group prefix ─────────────────────────────────────────────────────────


def test_group_prefix() -> None:
    """'drums' matches 'drums/kick' and 'drums/snare' as a group."""
    nodes = _nodes("drums/kick", "drums/snare", "bass")
    result = resolve_path("drums", nodes)
    assert isinstance(result, GroupPath)
    assert result.prefix == "drums"
    assert set(result.members) == {"drums/kick", "drums/snare"}


def test_group_does_not_match_partial_names() -> None:
    """'drum' should NOT match 'drums/kick' — prefix must be followed by '/'."""
    nodes = _nodes("drums/kick")
    result = resolve_path("drum", nodes)
    assert isinstance(result, UnknownPath)


# ── Unknown path ─────────────────────────────────────────────────────────


def test_unknown_node() -> None:
    nodes = _nodes("bass")
    result = resolve_path("nonexistent", nodes)
    assert result == UnknownPath("nonexistent")


def test_unknown_slashed_path_is_control() -> None:
    """'foo/bar' where 'foo' is not a node → ControlPath (engine-internal label passthrough)."""
    nodes = _nodes("bass")
    result = resolve_path("foo/bar", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "foo"
    assert result.param == "bar"
    assert result.label == "foo/bar"


# ── Edge cases ───────────────────────────────────────────────────────────


def test_empty_nodes() -> None:
    result = resolve_path("anything", {})
    assert result == UnknownPath("anything")


def test_deeply_nested_node_name() -> None:
    """Node named 'a/b/c' is exact match."""
    nodes = _nodes("a/b/c")
    result = resolve_path("a/b/c", nodes)
    assert result == NodePath("a/b/c")


def test_deeply_nested_control() -> None:
    """'a/b/c/param' where 'a/b/c' is a node → ControlPath."""
    nodes = _nodes("a/b/c")
    result = resolve_path("a/b/c/param", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "a/b/c"
    assert result.param == "param"


def test_ambiguous_depth_prefers_longest_node() -> None:
    """Both 'a' and 'a/b' are nodes. 'a/b/param' should resolve to ControlPath(node='a/b')."""
    nodes = _nodes("a", "a/b")
    result = resolve_path("a/b/param", nodes)
    assert isinstance(result, ControlPath)
    assert result.node == "a/b"
    assert result.param == "param"
