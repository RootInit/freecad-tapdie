import unittest

from tapdie import presets


class TestBoreLookup(unittest.TestCase):
    """Standard tap-drill sizes must map to the size they are drilled for."""

    CASES = [(2.5, 3.0), (3.3, 4.0), (4.2, 5.0), (5.0, 6.0),
             (6.8, 8.0), (8.5, 10.0), (10.2, 12.0), (14.0, 16.0),
             (17.5, 20.0), (21.0, 24.0)]

    def test_tap_drill_maps_to_its_nominal_size(self):
        for bore, expected in self.CASES:
            got, _pitch = presets.nearest_for_bore(bore)
            self.assertAlmostEqual(
                got, expected, places=3,
                msg="%.1fmm bore -> M%.0f, expected M%.0f"
                    % (bore, got, expected))

    def test_the_headline_case_picks_M8_not_M7(self):
        diameter, pitch = presets.nearest_for_bore(6.8)
        self.assertAlmostEqual(diameter, 8.0, places=3)
        self.assertAlmostEqual(pitch, 1.25, places=3)

    def test_naive_nearest_nominal_would_have_picked_M7(self):
        # Guards against anyone "simplifying" the lookup back to the bug.
        naive = min(presets.ISO_COARSE, key=lambda e: abs(e[0] - 6.8))
        self.assertAlmostEqual(naive[0], 7.0, places=3)


class TestShaftLookup(unittest.TestCase):
    def test_shaft_maps_to_its_own_nominal(self):
        for shaft in (6.0, 8.0, 10.0, 20.0):
            got, _ = presets.nearest_for_shaft(shaft)
            self.assertAlmostEqual(got, shaft, places=3)

    def test_slightly_undersize_shaft_still_maps_up(self):
        got, _ = presets.nearest_for_shaft(9.94)
        self.assertAlmostEqual(got, 10.0, places=3)


class TestFormDefaults(unittest.TestCase):
    def test_printed_is_ninety_degrees(self):
        self.assertAlmostEqual(presets.form_defaults("Printed 90")["angle"],
                               90.0, places=6)

    def test_iso_is_sixty_degrees(self):
        self.assertAlmostEqual(presets.form_defaults("ISO metric 60")["angle"],
                               60.0, places=6)

    def test_printed_lands_are_symmetric(self):
        d = presets.form_defaults("Printed 90")
        self.assertAlmostEqual(d["root_fraction"], d["crest_fraction"],
                               places=6)

    def test_iso_lands_are_the_standard_asymmetric_truncations(self):
        # H/8 truncation -> P/8 flat at the root; H/4 -> P/4 at the crest.
        d = presets.form_defaults("ISO metric 60")
        self.assertAlmostEqual(d["root_fraction"], 1.0 / 8.0, places=6)
        self.assertAlmostEqual(d["crest_fraction"], 1.0 / 4.0, places=6)

    def test_unrecognized_form_name_raises_ValueError(self):
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults("bogus")
        self.assertIn("has no preset", str(cm.exception))

    def test_form_custom_raises_ValueError(self):
        from tapdie import form
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults(form.CUSTOM)
        self.assertIn("has no preset", str(cm.exception))

    def test_none_form_name_raises_ValueError(self):
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults(None)
        self.assertIn("has no preset", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
