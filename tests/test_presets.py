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
    """The printed 90 form is NEAR-TRIANGULAR: the land is a pure fraction of
    pitch, and every remaining micron goes to depth.

    The lands exist only to avoid a mathematically sharp tip, which
    form.cutter_points rejects because a zero-width tip is the tangency case
    where consecutive turns of the sweep touch. They are not meant to be a
    measurable flat.

    An earlier version floored them at one extrusion width and it inverted
    its own purpose: measured across this table it left the thread shallower
    than 0.4mm at every size up to M10 -- 0.105mm on M4x0.7 -- buying a
    printable flat by producing an unprintable groove.
    """

    # (pitch, expected land) -- pinned exactly, so a change to LAND_FRACTION
    # has to update this deliberately rather than drifting.
    CASES = [
        (0.50, 0.0105),
        (0.70, 0.0147),
        (1.00, 0.0210),
        (1.25, 0.0263),
        (1.75, 0.0368),
        (3.80, 0.0798),
    ]

    def test_land_at_each_reference_pitch(self):
        for pitch, expected in self.CASES:
            d = presets.form_defaults("Printed 90", pitch)
            self.assertAlmostEqual(
                d["root_land"], expected, places=4,
                msg="pitch %.2f: expected %.4f, got %.4f"
                    % (pitch, expected, d["root_land"]))
            self.assertAlmostEqual(d["crest_land"], expected, places=4)

    def test_the_land_is_a_pure_fraction_of_pitch_at_every_size(self):
        for _diameter, pitch in presets.ISO_COARSE:
            d = presets.form_defaults("Printed 90", pitch)
            self.assertAlmostEqual(d["root_land"],
                                   presets.LAND_FRACTION * pitch, places=9,
                                   msg="pitch %.2f" % pitch)

    def test_the_groove_takes_almost_the_whole_pitch(self):
        """Near-triangular: at 90 degrees the flanks alone eat 2 x depth, so
        depth must come out just under half the pitch."""
        for _diameter, pitch in presets.ISO_COARSE:
            d = presets.form_defaults("Printed 90", pitch)
            depth = form.cut_depth(pitch, d["angle"], d["root_land"],
                                   d["crest_land"])
            self.assertGreater(depth, 0.47 * pitch,
                               "pitch %.2f only cut %.4f" % (pitch, depth))
            self.assertLess(depth, 0.5 * pitch)

    def test_depth_beats_the_old_floored_land_at_every_size(self):
        """The regression this replaced: M4x0.7 cut 0.105mm under the
        unconditional 0.4mm floor, a quarter of a nozzle."""
        d = presets.form_defaults("Printed 90", 0.7)
        depth = form.cut_depth(0.7, d["angle"], d["root_land"],
                               d["crest_land"])
        self.assertGreater(depth, 0.3)

    def test_a_coarse_pitch_stays_near_triangular_too(self):
        """printed_threads' own 3.8 pitch runs 0.08mm, well under one
        extrusion width, and prints fine."""
        d = presets.form_defaults("Printed 90", 3.8)
        self.assertAlmostEqual(d["root_land"], 0.0798, places=4)
        self.assertLess(d["root_land"], presets.NOZZLE)

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


class TestLargeDiameters(unittest.TestCase):
    """Reported: "with a large (100mm diameter) it does not automatically set
    the diameter that large, it seems to cap out at around 25".

    Two causes, both here: the table stopped at M24, and both lookups took
    the NEAREST entry, so everything past the end of the table snapped back
    to the largest size whatever it really measured.
    """

    def test_the_table_reaches_a_printable_maximum(self):
        # The bed is 256mm, so a 100mm thread is an ordinary thing to want.
        self.assertGreaterEqual(presets.ISO_COARSE[-1][0], 100.0)

    def test_the_table_is_ordered_and_has_no_duplicates(self):
        sizes = [d for d, _p in presets.ISO_COARSE]
        self.assertEqual(sizes, sorted(sizes))
        self.assertEqual(len(sizes), len(set(sizes)))

    def test_pitch_never_decreases_with_size(self):
        pitches = [p for _d, p in presets.ISO_COARSE]
        for a, b in zip(pitches, pitches[1:]):
            self.assertGreaterEqual(b, a)

    def test_a_100mm_shaft_is_not_capped(self):
        diameter, _pitch = presets.nearest_for_shaft(100.0)
        self.assertAlmostEqual(diameter, 100.0, places=6)

    def test_a_shaft_past_the_table_is_its_own_answer(self):
        """The shaft IS the major diameter, so there is nothing to snap to."""
        for size in (137.0, 200.0, 250.0):
            diameter, pitch = presets.nearest_for_shaft(size)
            self.assertAlmostEqual(diameter, size, places=6,
                                   msg="a %.0fmm shaft was capped at %.1f"
                                       % (size, diameter))
            self.assertGreater(pitch, 0.0)

    def test_a_bore_past_the_table_is_not_capped_either(self):
        for size in (95.0, 180.0):
            diameter, pitch = presets.nearest_for_bore(size)
            self.assertGreater(
                diameter, size,
                "a %.0fmm bore proposed a %.1fmm thread, which would not "
                "even reach its own wall" % (size, diameter))
            self.assertGreater(pitch, 0.0)

    def test_small_sizes_are_untouched_by_the_extension(self):
        """The lookups that already worked must keep their answers."""
        self.assertEqual(presets.nearest_for_shaft(8.0), (8.0, 1.25))
        self.assertEqual(presets.nearest_for_shaft(20.0), (20.0, 2.5))
        self.assertEqual(presets.nearest_for_bore(6.8)[0], 8.0)


if __name__ == "__main__":
    unittest.main()
