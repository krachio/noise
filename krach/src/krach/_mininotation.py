"""Mini-notation parser — TidalCycles-inspired pattern strings."""

from __future__ import annotations

from krach.pattern.pattern import Pattern, rest

from krach._patterns import hit, note


def p(notation: str, **kwargs: float) -> Pattern:
    """Parse mini-notation string into a Pattern.

    Syntax:
        p("x . x . x . . x")       # x=hit(), .=rest()
        p("C4 E4 G4 ~ C5")         # note names, ~=rest
        p("[C4 E4] G4 B4")         # []=simultaneous (Stack via |)
        p("C4*2 E4 G4")            # *N=repeat
        p("C4 E4", vel=0.5)        # kwargs passed to note()
    """
    tokens = _tokenize(notation)
    atoms = [_parse_token(t, **kwargs) for t in tokens]
    if not atoms:
        raise ValueError("empty pattern")
    if len(atoms) == 1:
        return atoms[0]
    result = atoms[0]
    for a in atoms[1:]:
        result = result + a
    return result


def _tokenize(s: str) -> list[str | list[str]]:
    """Split into tokens. [...] becomes a nested list."""
    tokens: list[str | list[str]] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c == "[":
            try:
                j = s.index("]", i)
            except ValueError:
                raise ValueError(f"unmatched '[' in pattern at position {i}") from None
            inner = s[i + 1 : j].split()
            tokens.append(inner)
            i = j + 1
        else:
            j = i
            while j < len(s) and not s[j].isspace() and s[j] != "[":
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _parse_token(token: str | list[str], **kwargs: float) -> Pattern:
    """Convert a token to a Pattern."""
    if isinstance(token, list):
        parts = [_parse_token(t, **kwargs) for t in token]
        result = parts[0]
        for part in parts[1:]:
            result = result | part
        return result

    # *N repeat suffix
    if "*" in token:
        base, count_str = token.rsplit("*", 1)
        try:
            count = int(count_str)
        except ValueError:
            raise ValueError(f"invalid repeat count '{count_str}' in '{token}'") from None
        if count < 1:
            raise ValueError(f"repeat count must be >= 1, got {count} in '{token}'")
        return _parse_token(base, **kwargs) * count

    # Rest tokens
    if token in (".", "~", "-"):
        return rest()

    # Hit trigger
    if token in ("x", "X"):
        return hit("gate", **kwargs)

    # Note name — validate before delegating to pitch parser
    import re
    if not re.match(r"^[A-G][#sb]?\d$", token):
        raise ValueError(
            f"invalid token {token!r} in mini-notation — "
            f"expected note (e.g. 'C4', 'Db3'), rest ('.', '~', '-'), or hit ('x')"
        )
    return note(token, **kwargs)
