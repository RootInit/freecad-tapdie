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
        self.assertAlmostEqual(
            presets.form_defaults("Printed 90", 3.8)["angle"], 90.0, places=6)

    def test_iso_is_sixty_degrees(self):
        self.assertAlmostEqual(
            presets.form_defaults("ISO metric 60", 1.25)["angle"], 60.0,
            places=6)

    def test_printed_lands_are_symmetric(self):
        d = presets.form_defaults("Printed 90", 3.8)
        self.assertAlmostEqual(d["root_land"], d["crest_land"], places=6)

    def test_iso_lands_are_the_standard_asymmetric_truncations(self):
        # H/8 truncation -> P/8 flat at the root; H/4 -> P/4 at the crest.
        # ISO is a pure fraction of pitch, unfloored/uncapped -- checked at
        # two different pitches so a stray hard-coded constant would show up.
        for pitch in (1.25, 3.0):
            d = presets.form_defaults("ISO metric 60", pitch)
            self.assertAlmostEqual(d["root_land"], pitch / 8.0, places=6)
            self.assertAlmostEqual(d["crest_land"], pitch / 4.0, places=6)

    def test_unrecognized_form_name_raises_ValueError(self):
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults("bogus", 1.0)
        self.assertIn("has no preset", str(cm.exception))

    def test_form_custom_raises_ValueError(self):
        from tapdie import form
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults(form.CUSTOM, 1.0)
        self.assertIn("has no preset", str(cm.exception))

    def test_none_form_name_raises_ValueError(self):
        with self.assertRaises(ValueError) as cm:
            presets.form_defaults(None, 1.0)
        self.assertIn("has no preset", str(cm.exception))


class TestPrintedLandFloorAndCap(unittest.TestCase):
    """The printed form's land must survive a change of pitch: a pure
    fraction (0.021 x pitch) collapses to a knife edge at a fine pitch, which
    is the exact defect a real M8x1.25 tap measurement surfaced (0.0262mm --
    about 1/15th of an extrusion width -- reported by the user as "does not
    have a flat bottom profile"). Floored at one extrusion width (NOZZLE),
    capped at LAND_CAP x pitch so the floor on both lands combined can never
    reach form.cutter_points' root_land + crest_land >= pitch guard.
    """

    # (pitch, expected land, floored-or-capped) -- all four pin an EXACT
    # value, not just "some floor applied", so a future tweak to the
    # constants is forced to update this table deliberately.
    CASES = [
        (0.50, 0.175, "capped"),   # LAND_CAP * 0.50
        (0.70, 0.245, "capped"),   # LAND_CAP * 0.70
        (1.25, 0.400, "floored"),  # NOZZLE; was 0.0262 before this fix
        (3.80, 0.400, "floored"),  # NOZZLE; was 0.0800 before this fix --
                                   # deliberately NOT restored to 0.08, see
                                   # presets.form_defaults's docstring.
    ]

    def test_land_at_each_reference_pitch(self):
        for pitch, expected, why in self.CASES:
            d = presets.form_defaults("Printed 90", pitch)
            self.assertAlmostEqual(
                d["root_land"], expected, places=3,
                msg="pitch %.2f: expected %s land %.3f, got %.4f"
                    % (pitch, why, expected, d["root_land"]))
            self.assertAlmostEqual(d["crest_land"], expected, places=3)

    def test_pitch_3_8_no_longer_matches_printed_threads_0_08mm(self):
        # Pin the deviation explicitly so nobody "fixes" it back: 0.08mm is
        # below one extrusion width and IS the defect the floor exists for.
        d = presets.form_defaults("Printed 90", 3.8)
        self.assertNotAlmostEqual(d["root_land"], 0.08, places=3)

    def test_land_sum_never_reaches_the_pitch_for_any_ISO_COARSE_pitch(self):
        # form.cutter_points rejects root_land + crest_land >= pitch. With
        # LAND_CAP=0.35 the two lands can sum to at most 0.7 x pitch, so this
        # must hold for every pitch this addon's own preset table offers,
        # not just the four spot-checked pitches above.
        for _diameter, pitch in presets.ISO_COARSE:
            d = presets.form_defaults("Printed 90", pitch)
            total = d["root_land"] + d["crest_land"]
            self.assertLess(
                total, pitch,
                "pitch %.2f: root_land + crest_land = %.4f reaches the "
                "pitch itself -- form.cutter_points would reject this"
                % (pitch, total))


if __name__ == "__main__":
    unittest.main()
