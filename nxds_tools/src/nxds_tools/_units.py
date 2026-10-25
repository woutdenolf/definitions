"""
A small parser of unit strings (spec §14): the UDUNITS-2 grammar with the unit
symbols of the index (``unit_symbols``, shipped as ``data/units.yaml``).
"""

import re
from collections import Counter
from functools import cache
from importlib import resources

import yaml

from .model import UnitSymbols

Dimensions = dict[str, int]
#: a unit string after normalisation: numeric factor and symbols with their powers
Normalised = tuple[float, tuple[tuple[str, int], ...]]

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
    r"|(?P<name>[A-Za-zµμÅ%][A-Za-z_µμÅ%0]*)"
    r"|(?P<op>\*\*|[*/^().·]|-?\d+))"
)


class UnitsError(ValueError):
    """A unit string that does not parse with the unit symbols."""


def unit_symbols() -> UnitSymbols:
    """The unit symbols shipped with the tools (published in the index)."""
    return _default_symbols()


def dimensions(units: str, symbols: UnitSymbols | None = None) -> Dimensions:
    """The dimensions of a unit string (``keV`` → ``{length: 2, mass: 1, time: -2}``)."""
    table = symbols or _default_symbols()
    result: Dimensions = {}
    for name, power in _parse(units)[1].items():
        for key, value in _unit(name, table).items():
            result[key] = result.get(key, 0) + value * power
    return {k: v for k, v in sorted(result.items()) if v}


def normalise(units: str, symbols: UnitSymbols | None = None) -> Normalised:
    """A unit string in a canonical form: ``m/s`` and ``m*s^-1`` are equal."""
    factor, names = _parse(units)
    dimensions(units, symbols)  # every symbol must be known
    return factor, tuple(sorted((k, v) for k, v in names.items() if v))


def format_dimensions(dims: Dimensions) -> str:
    """``length^2*mass*time^-2``; ``1`` when dimensionless."""
    if not dims:
        return "1"
    return "*".join(k if v == 1 else f"{k}^{v}" for k, v in sorted(dims.items()))


def empty_categories() -> list[str]:
    """Units categories that accept an empty unit string (§14)."""
    return list(_table().get("empty_categories", []))


@cache
def _table() -> dict:
    text = resources.files("nxds_tools").joinpath("data/units.yaml").read_text()
    return yaml.safe_load(text)


@cache
def _default_symbols() -> UnitSymbols:
    data = {k: v for k, v in _table().items() if k != "empty_categories"}
    return UnitSymbols.model_validate(data)


def _unit(name: str, table: UnitSymbols) -> Dimensions:
    if name in table.plain:
        return dict(table.plain[name])
    if name in table.prefixed:
        return dict(table.prefixed[name])
    for prefix in sorted(table.prefixes, key=len, reverse=True):
        if name.startswith(prefix) and name[len(prefix) :] in table.prefixed:
            return dict(table.prefixed[name[len(prefix) :]])
    match = re.fullmatch(r"([A-Za-zµμÅ]+?)(-?\d+)", name)
    if match:
        base = _unit(match.group(1), table)
        return {k: v * int(match.group(2)) for k, v in base.items()}
    raise UnitsError(f"unknown unit {name!r}")


def _parse(units: str) -> tuple[float, Counter]:
    text = units.strip()
    if text in ("", "1"):
        return 1.0, Counter()
    parser = _Parser(_tokens(text))
    result = parser.expression()
    if parser.pos != len(parser.tokens):
        raise UnitsError(f"cannot parse units {units!r}")
    return result


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            if text[pos].isspace():
                pos += 1
                continue
            raise UnitsError(f"cannot parse units {text!r}")
        kind = match.lastgroup or "op"
        tokens.append((kind, match.group(kind)))
        pos = match.end()
        # whitespace between two factors means multiplication
        if pos < len(text) and text[pos].isspace():
            tokens.append(("space", " "))
    while tokens and tokens[-1][0] == "space":
        tokens.pop()
    return tokens


_Term = tuple[float, Counter]


def _combine(left: _Term, right: _Term, sign: int) -> _Term:
    names = Counter(left[1])
    for key, value in right[1].items():
        names[key] += sign * value
    return left[0] * right[0] ** sign, names


def _power(term: _Term, exponent: int) -> _Term:
    return term[0] ** exponent, Counter({k: v * exponent for k, v in term[1].items()})


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def expression(self) -> _Term:
        result = self.factor()
        while (token := self._peek()) is not None:
            if token[1] in ("*", ".", "·") or token[0] == "space":
                self.pos += 1
                result = _combine(result, self.factor(), 1)
            elif token[1] == "/":
                self.pos += 1
                result = _combine(result, self.factor(), -1)
            else:
                break
        return result

    def factor(self) -> _Term:
        token = self._peek()
        if token is None:
            raise UnitsError("unexpected end of units")
        self.pos += 1
        base: _Term
        if token[1] == "(":
            base = self.expression()
            if self._peek() != ("op", ")"):
                raise UnitsError("unbalanced parenthesis")
            self.pos += 1
        elif token[0] == "num" or (
            token[0] == "op" and re.fullmatch(r"-?\d+", token[1])
        ):
            base = float(token[1]), Counter()
        elif token[0] == "name":
            base = 1.0, Counter({token[1]: 1})
            following = self._peek()
            if following is not None and re.fullmatch(r"-?\d+", following[1]):
                self.pos += 1
                return _power(base, int(following[1]))
        else:
            raise UnitsError(f"unexpected {token[1]!r}")
        token = self._peek()
        if token is not None and token[1] in ("^", "**"):
            self.pos += 1
            exponent = self._peek()
            if exponent is None:
                raise UnitsError("missing exponent")
            self.pos += 1
            value = exponent[1]
            if value == "(":
                value = self.tokens[self.pos][1]
                self.pos += 2
            try:
                base = _power(base, int(value))
            except ValueError as exc:
                raise UnitsError(f"bad exponent {value!r}") from exc
        return base
