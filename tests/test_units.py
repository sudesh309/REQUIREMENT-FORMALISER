"""Unit table, conversions, quantity parsing and the safe expression evaluator."""
import math
import unittest

from engine import units as U


class ConversionTests(unittest.TestCase):

    def assertClose(self, a, b, rel=1e-9):
        self.assertTrue(math.isclose(a, b, rel_tol=rel, abs_tol=1e-12), f"{a} != {b}")

    def test_avionics_units_are_in_the_table(self):
        symbols = {u["symbol"] for u in U.list_units()}
        for s in ("kg", "g", "lb", "W", "kW", "mW", "V", "mV", "A", "mA", "Hz", "kHz", "MHz", "GHz",
                  "s", "ms", "us", "ns", "m", "km", "ft", "nmi", "m/s", "kt", "ft/min", "deg", "rad",
                  "degC", "K", "bit", "byte", "kbit/s", "Mbit/s", "Gbit/s", "h", "FIT", "%", "Pa",
                  "kPa", "psi", "N", "lbf"):
            self.assertIn(s, symbols)

    def test_conversions(self):
        self.assertClose(U.convert(3, "lb", "kg"), 1.36077711)
        self.assertClose(U.convert(1, "nmi", "m"), 1852)
        self.assertClose(U.convert(100, "kt", "m/s"), 51.444444444)
        self.assertClose(U.convert(1000, "ft/min", "m/s"), 5.08)
        self.assertClose(U.convert(20, "degC", "K"), 293.15)
        self.assertClose(U.convert(212, "degF", "degC"), 100)
        self.assertClose(U.convert(180, "deg", "rad"), math.pi)
        self.assertClose(U.convert(1, "byte", "bit"), 8)
        self.assertClose(U.convert(100, "kbit/s", "bit/s"), 1e5)
        self.assertClose(U.convert(1, "Gbit/s", "Mbit/s"), 1000)
        self.assertClose(U.convert(14.6959, "psi", "kPa"), 101.325, rel=1e-5)
        self.assertClose(U.convert(1, "lbf", "N"), 4.4482216152605)
        self.assertClose(U.convert(1e9, "FIT", "1/h"), 1)
        self.assertClose(U.convert(50, "%", "1"), 0.5)
        self.assertClose(U.convert(2, "kW", "W"), 2000)
        self.assertClose(U.convert(5, "ms", "us"), 5000)

    def test_incompatible_units_rejected(self):
        with self.assertRaises(U.UnitError) as cm:
            U.convert(1, "psi", "kg")
        self.assertIn("pressure", str(cm.exception))
        self.assertIn("mass", str(cm.exception))
        self.assertFalse(U.compatible("W", "V"))
        self.assertTrue(U.compatible("kt", "km/h"))

    def test_aliases_and_compounds(self):
        self.assertEqual(U.normalize_unit("kts"), "kt")
        self.assertEqual(U.normalize_unit("µs"), "us")
        self.assertEqual(U.normalize_unit("Mbps"), "Mbit/s")
        self.assertEqual(U.normalize_unit(""), "")
        self.assertEqual(U.get_unit("kg/m^3").quantity, "density")
        self.assertClose(U.convert(1, "N*m", "J"), 1)
        self.assertClose(U.convert(2, "W/kg", "W/g"), 0.002)
        self.assertEqual(U.get_unit("1/s").quantity, "frequency / rate")
        with self.assertRaises(U.UnitError):
            U.normalize_unit("furlong")
        with self.assertRaises(U.UnitError):
            U.get_unit("degC/s")          # affine units cannot be combined

    def test_compatible_units_lists_same_dimension(self):
        mass = U.compatible_units("kg")
        self.assertIn("lb", mass)
        self.assertNotIn("W", mass)


class ParsingTests(unittest.TestCase):

    def test_parse_quantity(self):
        self.assertEqual(U.parse_quantity("2.5 lb"), (2.5, "lb"))
        self.assertEqual(U.parse_quantity("2.5lb"), (2.5, "lb"))
        self.assertEqual(U.parse_quantity("2*1.5 kW"), (3.0, "kW"))
        self.assertEqual(U.parse_quantity("1e3 Hz"), (1000.0, "Hz"))
        self.assertEqual(U.parse_quantity("10 ms"), (10, "ms"))
        self.assertEqual(U.parse_quantity("50%"), (50, "%"))
        self.assertEqual(U.parse_quantity("-40 degC"), (-40, "degC"))
        self.assertEqual(U.parse_quantity("(1 + 2) * 4"), (12, None))
        self.assertEqual(U.parse_quantity("250 kts"), (250, "kt"))
        self.assertEqual(U.parse_quantity("3 lb"), (3, "lb"))

    def test_parse_rejects_garbage(self):
        for bad in ("", "abc", "3 furlongs", "kg", "3 lb lb"):
            with self.subTest(bad=bad), self.assertRaises(U.UnitError):
                U.parse_quantity(bad)


class ExpressionTests(unittest.TestCase):

    def test_arithmetic(self):
        self.assertEqual(U.evaluate_expression("2*0.75"), 1.5)
        self.assertEqual(U.evaluate_expression("-(3 + 4) / 2"), -3.5)
        self.assertEqual(U.evaluate_expression("2**10"), 1024)
        self.assertEqual(U.evaluate_expression("7 // 2 + 7 % 2"), 4)

    def test_rejects_code(self):
        for expr in ("__import__('os')", "x + 1", "open('f')", "(1).real", "[1][0]",
                     "lambda: 1", "1 if 1 else 2", "'a' * 3", "True + 1", "9**9**9"):
            with self.subTest(expr=expr), self.assertRaises(U.UnitError):
                U.evaluate_expression(expr)

    def test_rejects_degenerate_values(self):
        with self.assertRaises(U.UnitError):
            U.evaluate_expression("1/0")
        with self.assertRaises(U.UnitError):
            U.evaluate_expression("1e308 * 10")
        with self.assertRaises(U.UnitError):
            U.evaluate_expression("1+" * 150 + "1")

    def test_format_number(self):
        self.assertEqual(U.format_number(1.3607771100000001), "1.36077711")
        self.assertEqual(U.format_number(3), "3")
        self.assertEqual(U.format_number(True), "true")

    def test_format_short_rounds_for_reading(self):
        """SU-11: 4.5359237 kg reads 4.54 kg; the stored value is not touched by formatting."""
        short = U.format_short
        self.assertEqual(short(4.5359237), "4.54")
        self.assertEqual(short(1234.5678), "1234.57")
        self.assertEqual(short(0.45359237), "0.454")            # below 1: three significant digits
        self.assertEqual(short(3.0), "3")                        # no trailing zeros
        self.assertEqual(short(4.50), "4.5")
        self.assertEqual(short(-2.7183), "-2.72")
        self.assertEqual(short(0), "0")
        self.assertEqual(short(31), "31")                        # whole numbers are exact
        self.assertEqual(short(1e-6), "1e-06")
        self.assertEqual(short(2.5e13), "2.5e+13")
        self.assertEqual(short(True), "true")
        value = 4.5359237
        short(value)
        self.assertEqual(value, 4.5359237)
        from kerml.stereotypes import format_short
        self.assertEqual(format_short(4.5359237, "kg"), "4.54 kg")
        self.assertEqual(format_short("A", ""), "A")
        self.assertEqual(format_short(None, "kg"), "")
        self.assertEqual(format_short(False), "false")


if __name__ == "__main__":
    unittest.main()
