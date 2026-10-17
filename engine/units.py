"""Physical units and safe numeric expressions for typed stereotype properties.

Standard library only. Every unit carries a *dimension* (exponents of mass,
length, time, current, temperature, angle and information) plus the factor
(and, for temperature scales, the offset) that converts it to SI::

    si_value = value * factor + offset

so two units are compatible exactly when their dimensions match. The table
covers what avionics architectures need (mass, power, electrical, timing,
frequency, navigation speeds and distances, pressures, data sizes and bus
rates, reliability in FIT and hours). Products and quotients of table units
(``kg/m^3``, ``N*m``, ``1/h``) are understood too.

Public API::

    get_unit("lb")                       -> Unit
    convert(2.5, "lb", "kg")             -> 1.1339809...
    parse_quantity("2*1.5 kW")           -> (3.0, "kW")
    evaluate_expression("(3 + 4) / 2")   -> 3.5     (numbers only, no names)
    list_units()                         -> [{"symbol", "name", "quantity", ...}]
"""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from typing import Optional, Union

Number = Union[int, float]

# Dimension vector: (mass, length, time, current, temperature, angle, information).
Dims = tuple[int, int, int, int, int, int, int]
_DIM_NAMES = ("kg", "m", "s", "A", "K", "rad", "bit")
DIMENSIONLESS: Dims = (0, 0, 0, 0, 0, 0, 0)


class UnitError(ValueError):
    """Unknown unit, incompatible conversion or invalid numeric expression."""


@dataclass(frozen=True)
class Unit:
    symbol: str
    name: str
    dims: Dims
    factor: float
    offset: float = 0.0

    @property
    def quantity(self) -> str:
        return quantity_name(self.dims)

    def to_si(self, value: float) -> float:
        return value * self.factor + self.offset

    def from_si(self, value: float) -> float:
        return (value - self.offset) / self.factor


def _d(m=0, l=0, t=0, i=0, th=0, a=0, b=0) -> Dims:  # noqa: E741
    return (m, l, t, i, th, a, b)


# Named quantities (first match wins when several share a dimension).
_QUANTITIES: list[tuple[str, Dims]] = [
    ("dimensionless", DIMENSIONLESS),
    ("mass", _d(m=1)),
    ("length", _d(l=1)),
    ("time", _d(t=1)),
    ("electric current", _d(i=1)),
    ("temperature", _d(th=1)),
    ("angle", _d(a=1)),
    ("information", _d(b=1)),
    ("frequency / rate", _d(t=-1)),
    ("data rate", _d(t=-1, b=1)),
    ("speed", _d(l=1, t=-1)),
    ("acceleration", _d(l=1, t=-2)),
    ("angular rate", _d(t=-1, a=1)),
    ("force", _d(m=1, l=1, t=-2)),
    ("pressure", _d(m=1, l=-1, t=-2)),
    ("energy", _d(m=1, l=2, t=-2)),
    ("power", _d(m=1, l=2, t=-3)),
    ("voltage", _d(m=1, l=2, t=-3, i=-1)),
    ("resistance", _d(m=1, l=2, t=-3, i=-2)),
    ("capacitance", _d(m=-1, l=-2, t=4, i=2)),
    ("inductance", _d(m=1, l=2, t=-2, i=-2)),
    ("electric charge", _d(t=1, i=1)),
    ("area", _d(l=2)),
    ("volume", _d(l=3)),
    ("density", _d(m=1, l=-3)),
    ("mass flow", _d(m=1, t=-1)),
    ("volume flow", _d(l=3, t=-1)),
]


def quantity_name(dims: Dims) -> str:
    for name, d in _QUANTITIES:
        if d == dims:
            return name
    parts = [f"{n}^{e}" if e != 1 else n for n, e in zip(_DIM_NAMES, dims) if e]
    return "·".join(parts) or "dimensionless"


_HOUR = 3600.0
_UNITS: dict[str, Unit] = {}
_ALIASES: dict[str, str] = {}


def _add(symbol: str, name: str, dims: Dims, factor: float, offset: float = 0.0,
         aliases: tuple[str, ...] = ()) -> None:
    _UNITS[symbol] = Unit(symbol, name, dims, float(factor), float(offset))
    for a in aliases:
        _ALIASES[a] = symbol


M, L, T, I, TH, ANG, INFO = (_d(m=1), _d(l=1), _d(t=1), _d(i=1), _d(th=1), _d(a=1), _d(b=1))

# --- dimensionless --------------------------------------------------------
_add("1", "one", DIMENSIONLESS, 1)
_add("%", "percent", DIMENSIONLESS, 0.01, aliases=("percent", "pct"))
_add("ppm", "parts per million", DIMENSIONLESS, 1e-6)
# --- mass -------------------------------------------------------------------
_add("kg", "kilogram", M, 1)
_add("g", "gram", M, 1e-3)
_add("mg", "milligram", M, 1e-6)
_add("t", "tonne", M, 1000)
_add("lb", "pound", M, 0.45359237, aliases=("lbs", "lbm"))
_add("oz", "ounce", M, 0.028349523125)
# --- length -----------------------------------------------------------------
_add("m", "metre", L, 1)
_add("mm", "millimetre", L, 1e-3)
_add("cm", "centimetre", L, 1e-2)
_add("km", "kilometre", L, 1e3)
_add("um", "micrometre", L, 1e-6, aliases=("µm", "μm"))
_add("ft", "foot", L, 0.3048, aliases=("feet",))
_add("in", "inch", L, 0.0254)
_add("yd", "yard", L, 0.9144)
_add("mi", "statute mile", L, 1609.344)
_add("nmi", "nautical mile", L, 1852, aliases=("NM", "nm_naut"))
# --- time -------------------------------------------------------------------
_add("s", "second", T, 1, aliases=("sec",))
_add("ms", "millisecond", T, 1e-3)
_add("us", "microsecond", T, 1e-6, aliases=("µs", "μs"))
_add("ns", "nanosecond", T, 1e-9)
_add("min", "minute", T, 60)
_add("h", "hour", T, _HOUR, aliases=("hr", "hrs"))
_add("d", "day", T, 86400, aliases=("day", "days"))
_add("yr", "year (365.25 d)", T, 365.25 * 86400, aliases=("year", "years"))
# --- frequency / rates ------------------------------------------------------
_add("Hz", "hertz", _d(t=-1), 1)
_add("kHz", "kilohertz", _d(t=-1), 1e3)
_add("MHz", "megahertz", _d(t=-1), 1e6)
_add("GHz", "gigahertz", _d(t=-1), 1e9)
_add("FIT", "failures in time (per 1e9 h)", _d(t=-1), 1 / (1e9 * _HOUR))
_add("1/h", "per hour", _d(t=-1), 1 / _HOUR, aliases=("/h", "per_h"))
# --- electrical -------------------------------------------------------------
_add("A", "ampere", I, 1)
_add("mA", "milliampere", I, 1e-3)
_add("uA", "microampere", I, 1e-6, aliases=("µA", "μA"))
_add("kA", "kiloampere", I, 1e3)
_add("V", "volt", _d(m=1, l=2, t=-3, i=-1), 1)
_add("mV", "millivolt", _d(m=1, l=2, t=-3, i=-1), 1e-3)
_add("uV", "microvolt", _d(m=1, l=2, t=-3, i=-1), 1e-6, aliases=("µV", "μV"))
_add("kV", "kilovolt", _d(m=1, l=2, t=-3, i=-1), 1e3)
_add("ohm", "ohm", _d(m=1, l=2, t=-3, i=-2), 1, aliases=("Ω", "Ohm"))
_add("kohm", "kiloohm", _d(m=1, l=2, t=-3, i=-2), 1e3, aliases=("kΩ",))
_add("Mohm", "megaohm", _d(m=1, l=2, t=-3, i=-2), 1e6, aliases=("MΩ",))
_add("F", "farad", _d(m=-1, l=-2, t=4, i=2), 1)
_add("uF", "microfarad", _d(m=-1, l=-2, t=4, i=2), 1e-6, aliases=("µF", "μF"))
_add("nF", "nanofarad", _d(m=-1, l=-2, t=4, i=2), 1e-9)
_add("pF", "picofarad", _d(m=-1, l=-2, t=4, i=2), 1e-12)
_add("H", "henry", _d(m=1, l=2, t=-2, i=-2), 1)
_add("mH", "millihenry", _d(m=1, l=2, t=-2, i=-2), 1e-3)
_add("uH", "microhenry", _d(m=1, l=2, t=-2, i=-2), 1e-6, aliases=("µH", "μH"))
_add("C", "coulomb", _d(t=1, i=1), 1)
_add("Ah", "ampere hour", _d(t=1, i=1), _HOUR, aliases=("A*h", "A·h"))
_add("mAh", "milliampere hour", _d(t=1, i=1), 3.6)
# --- power / energy ---------------------------------------------------------
_add("W", "watt", _d(m=1, l=2, t=-3), 1)
_add("mW", "milliwatt", _d(m=1, l=2, t=-3), 1e-3)
_add("kW", "kilowatt", _d(m=1, l=2, t=-3), 1e3)
_add("MW", "megawatt", _d(m=1, l=2, t=-3), 1e6)
_add("VA", "volt-ampere", _d(m=1, l=2, t=-3), 1)
_add("kVA", "kilovolt-ampere", _d(m=1, l=2, t=-3), 1e3)
_add("hp", "horsepower", _d(m=1, l=2, t=-3), 745.69987158227022)
_add("J", "joule", _d(m=1, l=2, t=-2), 1)
_add("kJ", "kilojoule", _d(m=1, l=2, t=-2), 1e3)
_add("Wh", "watt hour", _d(m=1, l=2, t=-2), _HOUR)
_add("kWh", "kilowatt hour", _d(m=1, l=2, t=-2), 1e3 * _HOUR)
# --- temperature (affine) ---------------------------------------------------
_add("K", "kelvin", TH, 1)
_add("degC", "degree Celsius", TH, 1, 273.15, aliases=("°C", "celsius", "Celsius"))
_add("degF", "degree Fahrenheit", TH, 5 / 9, 273.15 - 32 * 5 / 9,
     aliases=("°F", "fahrenheit", "Fahrenheit"))
# --- angle ------------------------------------------------------------------
_add("rad", "radian", ANG, 1)
_add("mrad", "milliradian", ANG, 1e-3)
_add("deg", "degree", ANG, math.pi / 180, aliases=("°", "degree", "degrees"))
_add("arcmin", "arc minute", ANG, math.pi / 180 / 60)
_add("arcsec", "arc second", ANG, math.pi / 180 / 3600)
_add("rev", "revolution", ANG, 2 * math.pi)
_add("deg/s", "degree per second", _d(t=-1, a=1), math.pi / 180)
_add("rad/s", "radian per second", _d(t=-1, a=1), 1)
_add("rpm", "revolution per minute", _d(t=-1, a=1), 2 * math.pi / 60)
# --- speed / acceleration ---------------------------------------------------
_add("m/s", "metre per second", _d(l=1, t=-1), 1)
_add("km/h", "kilometre per hour", _d(l=1, t=-1), 1000 / _HOUR, aliases=("kph",))
_add("kt", "knot", _d(l=1, t=-1), 1852 / _HOUR, aliases=("kn", "kts", "knot", "knots"))
_add("mph", "mile per hour", _d(l=1, t=-1), 0.44704)
_add("ft/s", "foot per second", _d(l=1, t=-1), 0.3048, aliases=("fps",))
_add("ft/min", "foot per minute", _d(l=1, t=-1), 0.3048 / 60, aliases=("fpm",))
_add("m/s^2", "metre per second squared", _d(l=1, t=-2), 1, aliases=("m/s2", "m/s²"))
_add("ft/s^2", "foot per second squared", _d(l=1, t=-2), 0.3048, aliases=("ft/s2", "ft/s²"))
_add("gn", "standard gravity", _d(l=1, t=-2), 9.80665, aliases=("g0", "G"))
# --- force / pressure -------------------------------------------------------
_add("N", "newton", _d(m=1, l=1, t=-2), 1)
_add("kN", "kilonewton", _d(m=1, l=1, t=-2), 1e3)
_add("lbf", "pound-force", _d(m=1, l=1, t=-2), 4.4482216152605)
_add("N*m", "newton metre", _d(m=1, l=2, t=-2), 1, aliases=("Nm", "N·m"))
_add("Pa", "pascal", _d(m=1, l=-1, t=-2), 1)
_add("hPa", "hectopascal", _d(m=1, l=-1, t=-2), 100)
_add("kPa", "kilopascal", _d(m=1, l=-1, t=-2), 1e3)
_add("MPa", "megapascal", _d(m=1, l=-1, t=-2), 1e6)
_add("bar", "bar", _d(m=1, l=-1, t=-2), 1e5)
_add("mbar", "millibar", _d(m=1, l=-1, t=-2), 100)
_add("psi", "pound per square inch", _d(m=1, l=-1, t=-2), 6894.757293168361)
_add("inHg", "inch of mercury", _d(m=1, l=-1, t=-2), 3386.389)
_add("mmHg", "millimetre of mercury", _d(m=1, l=-1, t=-2), 133.322387415)
_add("atm", "standard atmosphere", _d(m=1, l=-1, t=-2), 101325)
# --- information / data rates ----------------------------------------------
_add("bit", "bit", INFO, 1, aliases=("bits", "b"))
_add("byte", "byte", INFO, 8, aliases=("B", "bytes", "octet"))
_add("kbit", "kilobit", INFO, 1e3)
_add("Mbit", "megabit", INFO, 1e6)
_add("Gbit", "gigabit", INFO, 1e9)
_add("kB", "kilobyte", INFO, 8e3, aliases=("kbyte",))
_add("MB", "megabyte", INFO, 8e6, aliases=("Mbyte",))
_add("GB", "gigabyte", INFO, 8e9, aliases=("Gbyte",))
_add("KiB", "kibibyte", INFO, 8 * 1024)
_add("MiB", "mebibyte", INFO, 8 * 1024 ** 2)
_add("GiB", "gibibyte", INFO, 8 * 1024 ** 3)
_add("bit/s", "bit per second", _d(t=-1, b=1), 1, aliases=("bps", "b/s"))
_add("kbit/s", "kilobit per second", _d(t=-1, b=1), 1e3, aliases=("kbps", "kb/s"))
_add("Mbit/s", "megabit per second", _d(t=-1, b=1), 1e6, aliases=("Mbps", "Mb/s"))
_add("Gbit/s", "gigabit per second", _d(t=-1, b=1), 1e9, aliases=("Gbps", "Gb/s"))
_add("byte/s", "byte per second", _d(t=-1, b=1), 8, aliases=("B/s", "Bps"))
_add("kB/s", "kilobyte per second", _d(t=-1, b=1), 8e3, aliases=("kBps",))
_add("MB/s", "megabyte per second", _d(t=-1, b=1), 8e6, aliases=("MBps",))
# --- area / volume / flow ---------------------------------------------------
_add("m^2", "square metre", _d(l=2), 1, aliases=("m2", "m²"))
_add("cm^2", "square centimetre", _d(l=2), 1e-4, aliases=("cm2", "cm²"))
_add("mm^2", "square millimetre", _d(l=2), 1e-6, aliases=("mm2", "mm²"))
_add("ft^2", "square foot", _d(l=2), 0.09290304, aliases=("ft2", "ft²", "sqft"))
_add("in^2", "square inch", _d(l=2), 0.00064516, aliases=("in2", "in²", "sqin"))
_add("m^3", "cubic metre", _d(l=3), 1, aliases=("m3", "m³"))
_add("L", "litre", _d(l=3), 1e-3, aliases=("l", "liter", "litre"))
_add("mL", "millilitre", _d(l=3), 1e-6, aliases=("ml",))
_add("gal", "US gallon", _d(l=3), 0.003785411784)
_add("ft^3", "cubic foot", _d(l=3), 0.028316846592, aliases=("ft3", "ft³"))
_add("kg/m^3", "kilogram per cubic metre", _d(m=1, l=-3), 1, aliases=("kg/m3",))
_add("kg/s", "kilogram per second", _d(m=1, t=-1), 1)
_add("kg/h", "kilogram per hour", _d(m=1, t=-1), 1 / _HOUR)
_add("lb/h", "pound per hour", _d(m=1, t=-1), 0.45359237 / _HOUR, aliases=("pph",))
_add("L/min", "litre per minute", _d(l=3, t=-1), 1e-3 / 60, aliases=("lpm",))


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\s*(?:([*·/])\s*)?([^\s*·/^]+)(?:\^(-?\d+))?\s*")


def _compound(text: str) -> Optional[Unit]:
    """Products/quotients of table units, e.g. ``kg/m^3`` or ``N*m`` or ``1/h``."""
    pos, dims, factor, first = 0, [0] * 7, 1.0, True
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            return None
        op, sym, exp = m.group(1), m.group(2), int(m.group(3) or 1)
        if first and op:
            return None
        if not first and not op:
            return None
        sign = -1 if op == "/" else 1
        if sym == "1" and first:
            u = _UNITS["1"]
        else:
            sym = _ALIASES.get(sym, sym)
            u = _UNITS.get(sym)
            if u is None or u.offset:
                return None
        for k in range(7):
            dims[k] += sign * exp * u.dims[k]
        factor *= u.factor ** (sign * exp)
        pos, first = m.end(), False
    if first:
        return None
    return Unit(text, text, tuple(dims), factor)  # type: ignore[arg-type]


def normalize_unit(symbol: Optional[str]) -> str:
    """Canonical spelling of a unit (``''`` for none); raises UnitError when unknown."""
    if symbol is None:
        return ""
    s = str(symbol).strip()
    if not s:
        return ""
    if s in _UNITS:
        return s
    if s in _ALIASES:
        return _ALIASES[s]
    if _compound(s) is not None:
        return s
    raise UnitError(f"Unknown unit {s!r}")


def get_unit(symbol: str) -> Unit:
    s = normalize_unit(symbol)
    if not s:
        raise UnitError("No unit given")
    return _UNITS.get(s) or _compound(s)  # type: ignore[return-value]


def is_unit(symbol: str) -> bool:
    try:
        return bool(normalize_unit(symbol))
    except UnitError:
        return False


def compatible(a: str, b: str) -> bool:
    try:
        return get_unit(a).dims == get_unit(b).dims
    except UnitError:
        return False


def convert(value: Number, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` between compatible units; raises UnitError otherwise."""
    src, dst = get_unit(from_unit), get_unit(to_unit)
    if src.dims != dst.dims:
        raise UnitError(f"cannot convert {src.symbol} ({src.quantity}) to {dst.symbol} ({dst.quantity})")
    if src.symbol == dst.symbol:
        return float(value)
    return dst.from_si(src.to_si(float(value)))


def compatible_units(symbol: str) -> list[str]:
    """Table units with the same dimension as ``symbol`` (for unit pickers)."""
    try:
        dims = get_unit(symbol).dims
    except UnitError:
        return []
    return [u.symbol for u in _UNITS.values() if u.dims == dims and u.symbol != "1"]


def list_units() -> list[dict]:
    """Every table unit with its quantity, for pickers and documentation."""
    return [{"symbol": u.symbol, "name": u.name, "quantity": u.quantity,
             "factor": u.factor, "offset": u.offset,
             "aliases": sorted(a for a, s in _ALIASES.items() if s == u.symbol)}
            for u in _UNITS.values() if u.symbol != "1"]


# ---------------------------------------------------------------------------
# Safe arithmetic expressions (numbers only: no names, calls or attributes)
# ---------------------------------------------------------------------------

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_EXPR = 200


def evaluate_expression(text: str) -> Number:
    """Evaluate a simple arithmetic expression over numeric literals.

    Supports ``+ - * / // % **`` and parentheses. Names, calls, attributes,
    subscripts and everything else are rejected, so user input can never run
    code. Raises UnitError (a ValueError) with a readable message.
    """
    src = str(text).strip().replace("×", "*").replace("−", "-")
    if not src:
        raise UnitError("empty expression")
    if len(src) > _MAX_EXPR:
        raise UnitError(f"expression longer than {_MAX_EXPR} characters")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise UnitError(f"{text!r} is not a number or arithmetic expression") from None

    def ev(node: ast.AST) -> Number:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1e6):
                raise UnitError("exponent too large")
            try:
                return _BINOPS[type(node.op)](left, right)
            except ZeroDivisionError:
                raise UnitError("division by zero") from None
            except OverflowError:
                raise UnitError("numeric overflow") from None
        raise UnitError(f"{text!r} is not a number or arithmetic expression "
                        f"(only numbers, + - * / ** and parentheses are allowed)")

    value = ev(tree)
    if isinstance(value, complex) or not math.isfinite(value):
        raise UnitError(f"{text!r} does not evaluate to a finite number")
    return value


def parse_quantity(text: str) -> tuple[Number, Optional[str]]:
    """Split ``'2.5 lb'`` / ``'2*1.5kW'`` / ``'42'`` into (number, unit or None).

    The numeric part may be an arithmetic expression; the unit is the longest
    trailing text that is a known unit. Raises UnitError when nothing parses.
    """
    s = str(text).strip()
    if not s:
        raise UnitError("empty value")
    try:
        return evaluate_expression(s), None
    except UnitError as first_error:
        error = first_error
    for i in range(1, len(s)):
        unit_text, num_text = s[i:].strip(), s[:i].strip()
        if not num_text or not unit_text or unit_text[0] in "+-*/(.":
            continue
        if unit_text[0].isdigit() and unit_text != "1/h":
            continue
        try:
            unit = normalize_unit(unit_text)
        except UnitError:
            continue
        try:
            return evaluate_expression(num_text), unit
        except UnitError as ex:
            error = ex
            continue
    raise UnitError(f"{s!r} is not a number with an optional unit ({error})")


def format_number(value: Number, digits: int = 10) -> str:
    """Compact human form of a number (no float noise such as 1.3607771100000001)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}g}"
