import unittest

from tapdie import form, presets


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
        # The flat at the MAJOR diameter is P/8, at the MINOR P/4. Internal
        # threads crest at the minor, external at the major, so the pair
        # swaps between modes. Checked at two pitches so a stray hard-coded
        # constant would show up.
        for pitch in (1.25, 3.0):
            internal = presets.form_defaults("ISO metric 60", pitch,
                                             form.INTERNAL)
            self.assertAlmostEqual(internal["root_land"], pitch / 8.0,
                                   places=6)
            self.assertAlmostEqual(internal["crest_land"], pitch / 4.0,
                                   places=6)

    def test_iso_truncations_swap_for_an_external_thread(self):
        # The bug this guards: both modes used to return the internal
        # assignment, giving every ISO external thread a P/4 crest where the
        # standard wants P/8. Depth depends only on the sum, so nothing that
        # measured depth could catch it.
        for pitch in (1.25, 3.0):
            external = presets.form_defaults("ISO metric 60", pitch,
                                             form.EXTERNAL)
            self.assertAlmostEqual(external["crest_land"], pitch / 8.0,
                                   places=6)
            self.assertAlmostEqual(external["root_land"], pitch / 4.0,
                                   places=6)

    def test_iso_land_sum_is_mode_independent(self):
        # ...which is exactly why the swap was invisible: the depth the two
        # produce is identical.
        for pitch in (1.25, 3.0):
            a = presets.form_defaults("ISO metric 60", pitch, form.INTERNAL)
            b = presets.form_defaults("ISO metric 60", pitch, form.EXTERNAL)
            self.assertAlmostEqual(a["root_land"] + a["crest_land"],
                                   b["root_land"] + b["crest_land"],
                                   places=9)

    def test_printed_lands_do_not_swap(self):
        # The printed form is symmetric, so mode must make no difference.
        a = presets.form_defaults("Printed 90", 1.25, form.INTERNAL)
        b = presets.form_defaults("Printed 90", 1.25, form.EXTERNAL)
        self.assertEqual(a, b)

    def test_iso_rejects_a_bogus_mode(self):
        with self.assertRaises(ValueError):
            presets.form_defaults("ISO metric 60", 1.25, "Bogus")

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
    """The land takes one extrusion width where the pitch can afford it, and
    yields to thread DEPTH where it cannot.

    Both compete for the same budget --
    pitch = crest + root + 2 * depth * tan(angle/2) -- so an unconditional
    NOZZLE floor buys its printable flat straight out of the groove. It left
    the thread shallower than one extrusion width at every size up to M10
    (0.105mm of depth on M4x0.7), which no slicer resolves.
    """

    # (pitch, expected land, what bound it) -- every case pins an EXACT
    # value, so a tweak to the constants is forced to update this
    # deliberately rather than drifting.
    CASES = [
        (0.50, 0.0105, "depth: pitch cannot afford any land"),
        (0.70, 0.0147, "depth: pitch cannot afford any land"),
        (1.00, 0.1000, "depth: exactly one extrusion width of groove"),
        (1.25, 0.2250, "depth: exactly one extrusion width of groove"),
        (1.75, 0.4000, "NOZZLE floor, now affordable"),
        (3.80, 0.4000, "NOZZLE floor"),
    ]

    def test_land_at_each_reference_pitch(self):
        for pitch, expected, why in self.CASES:
            d = presets.form_defaults("Printed 90", pitch)
            self.assertAlmostEqual(
                d["root_land"], expected, places=4,
                msg="pitch %.2f: expected %.4f (%s), got %.4f"
                    % (pitch, expected, why, d["root_land"]))
            self.assertAlmostEqual(d["crest_land"], expected, places=4)

    def test_depth_reaches_one_extrusion_width_wherever_the_pitch_allows(self):
        """The whole point of letting the land yield.

        At 90 degrees the flanks alone need 2 * depth of pitch, so a 0.4mm
        groove needs 0.8mm of pitch before any land is affordable. Above
        that threshold the depth must actually get there.
        """
        for _diameter, pitch in presets.ISO_COARSE:
            d = presets.form_defaults("Printed 90", pitch)
            depth = form.cut_depth(pitch, d["angle"], d["root_land"],
                                   d["crest_land"])
            if pitch > 2.0 * presets.NOZZLE:
                self.assertGreaterEqual(
                    depth, presets.NOZZLE - 1e-9,
                    "pitch %.2f can afford a %.2fmm groove but only cut "
                    "%.4f" % (pitch, presets.NOZZLE, depth))

    def test_a_pitch_too_fine_for_any_land_still_maximises_depth(self):
        # Below 2 * NOZZLE * tan the groove cannot reach one extrusion width
        # whatever we do, so the land drops to the near-sharp fraction and
        # every remaining micron goes to depth.
        for pitch in (0.5, 0.7, 0.8):
            d = presets.form_defaults("Printed 90", pitch)
            self.assertAlmostEqual(d["root_land"],
                                   presets.LAND_FRACTION * pitch, places=6)

    def test_the_land_never_costs_more_than_the_groove_is_worth(self):
        # Regression on the specific numbers: M4x0.7 cut 0.105mm of depth
        # under the unconditional floor, a quarter of a nozzle.
        d = presets.form_defaults("Printed 90", 0.7)
        depth = form.cut_depth(0.7, d["angle"], d["root_land"],
                               d["crest_land"])
        self.assertGreater(depth, 0.3)

    def test_a_coarse_pitch_still_gets_the_full_extrusion_width_land(self):
        # The floor is not abandoned -- only deferred to where it is
        # affordable. printed_threads' own 3.8 pitch keeps it.
        d = presets.form_defaults("Printed 90", 3.8)
        self.assertAlmostEqual(d["root_land"], presets.NOZZLE, places=6)

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
