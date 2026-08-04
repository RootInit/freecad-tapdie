import math
import unittest

from tapdie import form


class TestDepth(unittest.TestCase):
    """depth() is the UNTRUNCATED reference depth, not what the cutter cuts."""

    def test_printed_v_spends_whole_pitch_on_flanks(self):
        # At 45 deg flanks the two flanks alone eat the pitch, so depth = P/2.
        d = form.depth(form.PRINTED, 3.8, 90.0, form.INTERNAL)
        self.assertAlmostEqual(d, 1.9, places=6)

    def test_printed_depth_tracks_angle(self):
        d = form.depth(form.PRINTED, 3.8, 60.0, form.INTERNAL)
        self.assertAlmostEqual(d, 3.8 / (2 * math.tan(math.radians(30))), places=6)

    def test_iso_internal_is_five_eighths_H(self):
        H = 1.25 * math.sqrt(3) / 2
        d = form.depth(form.ISO, 1.25, 60.0, form.INTERNAL)
        self.assertAlmostEqual(d, 5 * H / 8, places=6)
        self.assertAlmostEqual(d, 0.5413 * 1.25, places=3)

    def test_iso_external_is_seventeen_twentyfourths_H(self):
        H = 1.25 * math.sqrt(3) / 2
        d = form.depth(form.ISO, 1.25, 60.0, form.EXTERNAL)
        self.assertAlmostEqual(d, 17 * H / 24, places=6)


class TestCutDepth(unittest.TestCase):
    def test_obeys_the_profile_identity(self):
        # pitch = crest_land + root_land + 2 * depth * tan(angle/2)
        p, angle, root, crest = 1.25, 90.0, 0.2, 0.3
        d = form.cut_depth(p, angle, root, crest)
        tan = math.tan(math.radians(angle / 2))
        self.assertAlmostEqual(crest + root + 2 * d * tan, p, places=9)

    def test_zero_lands_collapse_to_the_sharp_v_depth(self):
        self.assertAlmostEqual(form.cut_depth(3.8, 90.0, 0.0, 0.0),
                               form.depth(form.PRINTED, 3.8, 90.0,
                                          form.INTERNAL),
                               places=9)

    def test_iso_basic_depth_agrees_with_five_eighths_H(self):
        # The ISO basic profile's own truncations, fed back in, must
        # reproduce 5H/8 -- the check that the land table is self-consistent.
        p = 1.25
        H = p * math.sqrt(3) / 2
        d = form.cut_depth(p, 60.0, root_land=p / 8.0, crest_land=p / 4.0)
        self.assertAlmostEqual(d, 5 * H / 8, places=9)


class TestRadialOffset(unittest.TestCase):
    """c / sin(a/2), NOT c * sec(a/2). The two agree only at 90 degrees."""

    def test_offset_opens_the_requested_normal_gap(self):
        # Shift the V radially by the offset; the perpendicular distance
        # between the old and new flank must come back out as `clearance`.
        for angle in (60.0, 90.0, 120.0):
            c = 0.12
            half = math.radians(angle / 2.0)
            shift = form.radial_offset(c, angle)
            # A flank through the apex has direction (cos, sin) in (r, v);
            # displacing the apex by `shift` along r moves the line by
            # shift * sin(a/2) perpendicular to itself.
            self.assertAlmostEqual(shift * math.sin(half), c, places=9,
                                   msg="angle %.0f" % angle)

    def test_the_sec_form_is_wrong_away_from_ninety(self):
        c = 0.12
        for angle, agree in ((90.0, True), (60.0, False), (120.0, False)):
            sec = 1.0 / math.cos(math.radians(angle / 2.0))
            same = abs(form.radial_offset(c, angle) - c * sec) < 1e-9
            self.assertEqual(same, agree,
                             "angle %.0f: sec form %s"
                             % (angle, "should" if agree else "should not"))

    def test_iso_sixty_differs_by_seventy_three_percent(self):
        c = 0.12
        sec = 1.0 / math.cos(math.radians(30.0))
        self.assertAlmostEqual(form.radial_offset(c, 60.0), 2.0 * c, places=9)
        self.assertAlmostEqual(c * sec, 0.1386, places=4)

    def test_zero_clearance_is_zero_offset(self):
        self.assertEqual(form.radial_offset(0.0, 90.0), 0.0)


class TestSpan(unittest.TestCase):
    """Where the threaded run sits relative to the selected circle."""

    def test_both_straddles_the_anchor(self):
        self.assertEqual(form.span(form.BOTH, 10.0), (-5.0, 5.0))

    def test_forward_starts_at_the_anchor(self):
        self.assertEqual(form.span(form.FORWARD, 10.0), (0.0, 10.0))

    def test_reverse_ends_at_the_anchor(self):
        self.assertEqual(form.span(form.REVERSE, 10.0), (-10.0, 0.0))

    def test_every_direction_spans_exactly_the_length(self):
        for direction in form.DIRECTIONS:
            lo, hi = form.span(direction, 7.5)
            self.assertAlmostEqual(hi - lo, 7.5, places=9,
                                   msg="direction %s" % direction)

    def test_only_both_crosses_the_anchor(self):
        # The point of the feature: a one-way run must not put half the
        # cutter on the wrong side of the circle the user picked.
        self.assertLess(form.span(form.BOTH, 4.0)[0], 0.0)
        self.assertGreater(form.span(form.BOTH, 4.0)[1], 0.0)
        for direction in (form.FORWARD, form.REVERSE):
            lo, hi = form.span(direction, 4.0)
            self.assertTrue(lo >= 0.0 or hi <= 0.0,
                            "%s crosses the anchor" % direction)

    def test_unknown_direction_is_rejected(self):
        with self.assertRaises(form.ProfileError) as ctx:
            form.span("Sideways", 10.0)
        self.assertIn("is not one of", str(ctx.exception))

    def test_non_positive_length_is_rejected(self):
        for length in (0.0, -1.0):
            with self.assertRaises(form.ProfileError) as ctx:
                form.span(form.BOTH, length)
            self.assertIn("must be positive", str(ctx.exception))


class TestCrestRadius(unittest.TestCase):
    def test_external_shaves_the_shaft(self):
        r = form.crest_radius(form.EXTERNAL, 4.0, 0.12, 90.0)
        self.assertAlmostEqual(r, 4.0 - form.radial_offset(0.12, 90.0),
                               places=9)
        self.assertAlmostEqual(r, 3.8303, places=4)

    def test_internal_opens_the_bore(self):
        r = form.crest_radius(form.INTERNAL, 3.375, 0.12, 90.0)
        self.assertAlmostEqual(r, 3.375 + form.radial_offset(0.12, 90.0),
                               places=9)

    def test_zero_clearance_leaves_the_surface_alone(self):
        for mode in (form.INTERNAL, form.EXTERNAL):
            self.assertAlmostEqual(
                form.crest_radius(mode, 4.0, 0.0, 90.0), 4.0, places=9)

    def test_a_mated_pair_ends_up_with_twice_the_clearance_between_flanks(self):
        """The whole point of taking clearance radially.

        A bolt and a nut cut with the same settings have their profiles
        displaced by 2 * radial_offset, which is a flank gap of exactly
        2 * clearance -- CLAUDE.md's 0.2-0.4mm total, split between the two.
        """
        c, angle = 0.12, 90.0
        displacement = 2.0 * form.radial_offset(c, angle)
        gap = displacement * math.sin(math.radians(angle / 2.0))
        self.assertAlmostEqual(gap, 2.0 * c, places=9)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            form.crest_radius("Bogus", 4.0, 0.12, 90.0)


class TestCutterPoints(unittest.TestCase):
    """The profile is anchored on the SURFACE, not on Diameter."""

    # Clearance deliberately 0 here so the lands come out exactly as asked
    # and the pure geometry is readable; TestClearance covers the offset.
    KW = dict(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
              pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
              clearance=0.0, surface_radius=8.2597, overrun=1.0)

    def points(self, **over):
        kw = dict(self.KW)
        kw.update(over)
        return form.cutter_points(
            kw["mode"], kw["form_name"], kw["diameter"], kw["pitch"],
            kw["angle"], kw["root_land"], kw["crest_land"], kw["clearance"],
            kw["surface_radius"], kw["overrun"])

    def test_returns_six_corners(self):
        self.assertEqual(len(self.points()), 6)

    def test_shoulder_sits_exactly_on_the_surface(self):
        """THE shelf regression guard, internal.

        Any gap between the shoulder and the surface is filled by the
        cutter's parallel section, which cuts a flat annular shelf between
        every pair of turns instead of a flank -- 0.3697mm of it, measured,
        before this was pinned.
        """
        pts = self.points()
        self.assertAlmostEqual(pts[1][0], self.KW["surface_radius"], places=9)
        self.assertAlmostEqual(pts[4][0], self.KW["surface_radius"], places=9)

    def test_shoulder_sits_exactly_on_the_surface_external(self):
        """The same guard, external -- both modes had the shelf."""
        pts = self.points(mode=form.EXTERNAL, surface_radius=10.0)
        self.assertAlmostEqual(pts[1][0], 10.0, places=9)
        self.assertAlmostEqual(pts[4][0], 10.0, places=9)

    def test_shoulder_holds_the_surface_when_diameter_is_wrong(self):
        """Diameter must not be able to reintroduce the shelf.

        The old construction placed the profile from Diameter and a separate
        depth(), so any disagreement with the real surface became shelf.
        Sweeping Diameter across a wide range must now move nothing.
        """
        reference = self.points(diameter=20.0)
        for diameter in (4.0, 12.0, 20.0, 50.0, 200.0):
            pts = self.points(diameter=diameter)
            self.assertEqual(pts, reference,
                             "Diameter=%.1f moved the profile" % diameter)

    def test_root_land_is_the_requested_width(self):
        pts = self.points()
        self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.08, places=9)

    def test_parallel_section_is_pitch_minus_crest_land(self):
        pts = self.points()
        self.assertAlmostEqual(pts[2][1] - pts[3][1], 3.8 - 0.08, places=9)

    def test_depth_obeys_the_profile_identity(self):
        pts = self.points()
        tip, shoulder = pts[0][0], pts[1][0]
        self.assertAlmostEqual(abs(tip - shoulder),
                               form.cut_depth(3.8, 90.0, 0.08, 0.08),
                               places=9)

    def test_lands_are_independent(self):
        """ISO needs P/8 at the root and P/4 at the crest simultaneously."""
        pts = self.points(pitch=1.25, root_land=0.15625, crest_land=0.3125,
                          angle=60.0, form_name=form.ISO, diameter=8.0,
                          surface_radius=3.3234)
        self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.15625, places=9)
        self.assertAlmostEqual(pts[2][1] - pts[3][1], 1.25 - 0.3125, places=9)

    def test_flank_is_at_the_half_angle(self):
        pts = self.points()
        tip, shoulder = pts[0], pts[1]
        # atan2(dr, dz) measures the flank OFF THE AXIS, which is
        # 90 - angle/2, not angle/2. The two coincide at 90 degrees and
        # nowhere else, so a test written only at 90 cannot tell them apart
        # -- this project has already been bitten by exactly that.
        dr = abs(shoulder[0] - tip[0])
        dz = abs(shoulder[1] - tip[1])
        self.assertAlmostEqual(math.degrees(math.atan2(dr, dz)),
                               90.0 - 90.0 / 2.0, places=6)

    def test_flank_angle_survives_clearance(self):
        """Clearance must offset the flank, not rotate it.

        Widening by c*sec while deepening by c is the only pair that leaves
        the angle alone; the old radial-apex shift did not, except at 90 deg.
        Swept across three angles precisely so the 90 degree coincidence
        above cannot hide a convention error.
        """
        for angle in (60.0, 90.0, 120.0):
            pts = self.points(angle=angle, clearance=0.05, root_land=0.3,
                              crest_land=0.5)
            tip, shoulder = pts[0], pts[1]
            dr = abs(shoulder[0] - tip[0])
            dz = abs(shoulder[1] - tip[1])
            self.assertAlmostEqual(math.degrees(math.atan2(dr, dz)),
                                   90.0 - angle / 2.0, places=6,
                                   msg="angle %.0f" % angle)

    def test_external_mirrors_outward(self):
        pts = self.points(mode=form.EXTERNAL, surface_radius=10.0,
                          diameter=20.0)
        self.assertLess(pts[0][0], pts[1][0])   # tip inside shoulder
        self.assertLess(pts[1][0], pts[2][0])   # shoulder inside far end

    def test_lands_summing_past_the_pitch_are_rejected(self):
        # The tip must stay inside the shoulder: root_land + crest_land < P.
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(root_land=2.0, crest_land=2.0)
        self.assertIn("leaves no flank", str(ctx.exception))

    def test_zero_root_land_is_rejected(self):
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(root_land=0.0)
        self.assertIn("sharp edge", str(ctx.exception))

    def test_zero_crest_land_is_rejected(self):
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(crest_land=0.0)
        self.assertIn("sharp edge", str(ctx.exception))


class TestClearance(unittest.TestCase):
    """Clearance is RADIAL: it moves the whole profile, never the lands."""

    KW = dict(mode=form.EXTERNAL, form_name=form.PRINTED, diameter=8.0,
              pitch=1.25, angle=90.0, root_land=0.4, crest_land=0.4,
              clearance=0.0, surface_radius=4.0, overrun=1.0)

    def points(self, **over):
        kw = dict(self.KW)
        kw.update(over)
        return form.cutter_points(
            kw["mode"], kw["form_name"], kw["diameter"], kw["pitch"],
            kw["angle"], kw["root_land"], kw["crest_land"], kw["clearance"],
            kw["surface_radius"], kw["overrun"])

    def test_lands_are_untouched_at_every_clearance(self):
        """THE reason clearance is radial rather than axial.

        Taken axially, 0.12 of clearance ate 0.34mm of a 0.4mm crest land
        and made every pitch below M8 unbuildable. Taken radially it costs
        the lands nothing, at any value.
        """
        for c in (0.0, 0.05, 0.12, 0.3, 0.5):
            pts = self.points(clearance=c)
            self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.4, places=9,
                                   msg="root land at clearance %.2f" % c)
            self.assertAlmostEqual(1.25 - (pts[2][1] - pts[3][1]), 0.4,
                                   places=9,
                                   msg="crest land at clearance %.2f" % c)

    def test_shifts_the_whole_profile_radially(self):
        c = 0.12
        shift = form.radial_offset(c, 90.0)
        plain, offset = self.points(), self.points(clearance=c)
        for i, (a, b) in enumerate(zip(plain, offset)):
            if i in (2, 3):
                continue   # `far` is anchored on the ORIGINAL surface
            self.assertAlmostEqual(a[0] - b[0], shift, places=9,
                                   msg="corner %d did not shift" % i)

    def test_shoulder_tracks_the_relieved_surface(self):
        """The shelf guard, restated for a nonzero clearance."""
        for c in (0.0, 0.05, 0.12, 0.3):
            pts = self.points(clearance=c)
            expected = form.crest_radius(form.EXTERNAL, 4.0, c, 90.0)
            self.assertAlmostEqual(pts[1][0], expected, places=9,
                                   msg="clearance %.2f" % c)

    def test_groove_depth_is_independent_of_clearance(self):
        for c in (0.0, 0.12, 0.3):
            pts = self.points(clearance=c)
            self.assertAlmostEqual(pts[1][0] - pts[0][0],
                                   form.cut_depth(1.25, 90.0, 0.4, 0.4),
                                   places=9, msg="clearance %.2f" % c)

    def test_the_far_end_still_clears_the_unrelieved_surface(self):
        # Otherwise the cutter would stop short of the original shaft and
        # leave an uncut collar wherever the relief did not reach.
        pts = self.points(clearance=0.12)
        self.assertAlmostEqual(pts[2][0], 4.0 + 1.0, places=9)

    def test_clearance_deeper_than_the_shaft_is_rejected(self):
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(clearance=20.0)
        self.assertIn("deeper than the shaft", str(ctx.exception))


class TestCriticalValidation(unittest.TestCase):
    """Test input validation for critical error modes."""

    KW = dict(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
              pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
              clearance=0.0, surface_radius=8.2597, overrun=1.0)

    def points(self, **over):
        kw = dict(self.KW)
        kw.update(over)
        return form.cutter_points(
            kw["mode"], kw["form_name"], kw["diameter"], kw["pitch"],
            kw["angle"], kw["root_land"], kw["crest_land"], kw["clearance"],
            kw["surface_radius"], kw["overrun"])

    def test_overrun_zero_is_rejected_internal(self):
        """Overrun must be positive to reach past the surface."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(overrun=0.0)
        self.assertIn("must be positive", str(ctx.exception))

    def test_overrun_negative_is_rejected_internal(self):
        """Negative overrun would fold the profile inward."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(overrun=-1.0)
        self.assertIn("must be positive", str(ctx.exception))

    def test_overrun_zero_is_rejected_external(self):
        """Overrun must be positive in external mode too."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode=form.EXTERNAL, surface_radius=10.0, overrun=0.0)
        self.assertIn("must be positive", str(ctx.exception))

    def test_overrun_negative_is_rejected_external(self):
        """Negative overrun collapses the external profile."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode=form.EXTERNAL, surface_radius=10.0, overrun=-1.0)
        self.assertIn("must be positive", str(ctx.exception))

    def test_overrun_larger_than_the_bore_is_rejected_internal(self):
        """An overrun past the axis folds the profile through it."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(overrun=10.0)
        self.assertIn("reaches through the axis", str(ctx.exception))

    def test_external_thread_deeper_than_shaft_is_rejected(self):
        """EXTERNAL where the cut depth exceeds the shaft radius."""
        # pitch 30 on a 5mm-radius shaft: the flanks alone need ~14.6mm of
        # depth, so the tip lands behind the axis. crest_land is raised off
        # the 0.08 default so the cutter-width guard does not fire first.
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode=form.EXTERNAL, form_name=form.PRINTED,
                        diameter=10.0, pitch=30.0, angle=90.0,
                        crest_land=1.0, surface_radius=5.0)
        self.assertIn("deeper than the shaft", str(ctx.exception))

    def test_invalid_mode_is_rejected(self):
        """Mode must be INTERNAL or EXTERNAL, not a typo."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode="Bogus")
        self.assertIn("is not", str(ctx.exception))

    def test_invalid_mode_case_sensitivity(self):
        """Mode matching is case-sensitive."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode="internal")
        self.assertIn("is not", str(ctx.exception))

    def test_invalid_form_name_is_rejected(self):
        """Form name must be one of FORMS."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(form_name="Bogus")
        self.assertIn("is not one of", str(ctx.exception))

    def test_invalid_form_name_typo(self):
        """Typos in form name are caught."""
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(form_name="Printed 90x")
        self.assertIn("is not one of", str(ctx.exception))


class TestRequiredSurfaceRadius(unittest.TestCase):
    def test_external_is_just_the_nominal_radius(self):
        r = form.required_surface_radius(form.EXTERNAL, 8.0, 1.25, 90.0,
                                         0.4, 0.4, 0.12)
        self.assertAlmostEqual(r, 4.0, places=9)

    def test_internal_leaves_room_for_depth_and_both_reliefs(self):
        r = form.required_surface_radius(form.INTERNAL, 8.0, 1.25, 90.0,
                                         0.4, 0.4, 0.12)
        self.assertAlmostEqual(
            r, 4.0 - form.cut_depth(1.25, 90.0, 0.4, 0.4)
            - 2.0 * form.radial_offset(0.12, 90.0), places=9)

    def test_a_mated_pair_meets_crest_to_root(self):
        """The nut's root must land exactly on the bolt's crest.

        Bolt from a nominal shaft:  crest = D/2 - offset
        Nut from the required bore: root  = bore + offset + cut_depth
        """
        d, p, angle, root_l, crest_l, c = 8.0, 1.25, 90.0, 0.4, 0.4, 0.12
        offset = form.radial_offset(c, angle)
        bolt_crest = form.crest_radius(form.EXTERNAL, d / 2.0, c, angle)
        bore = form.required_surface_radius(form.INTERNAL, d, p, angle,
                                            root_l, crest_l, c)
        nut_root = (form.crest_radius(form.INTERNAL, bore, c, angle)
                    + form.cut_depth(p, angle, root_l, crest_l))
        self.assertAlmostEqual(nut_root, bolt_crest, places=9)
        self.assertGreater(offset, 0.0)

    def test_a_printed_90_bore_is_larger_than_the_iso_tap_drill(self):
        # M8x1.25: the ISO 60 deg tap drill is 6.75mm. A 90 deg printed form
        # of the same nominal size wants 6.871mm -- larger, because its
        # shallower V needs less depth, but close enough that the ISO drill
        # is a usable starting guess rather than a wild one.
        r = form.required_surface_radius(form.INTERNAL, 8.0, 1.25, 90.0,
                                         0.4, 0.4, 0.12)
        self.assertAlmostEqual(2 * r, 6.8712, places=4)
        self.assertGreater(2 * r, 6.75)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            form.required_surface_radius("Bogus", 8.0, 1.25, 90.0,
                                         0.4, 0.4, 0.12)


class TestAchievedDiameter(unittest.TestCase):
    """The inverse of required_surface_radius -- the check that makes
    `Diameter` mean something.

    Swept across 60, 90 and 120 degrees, never at 90 alone: at 90 the flank
    half-angle coincidences make a wrong convention indistinguishable from a
    right one (see CLAUDE.md's "45 degree coincidence"), so a single-angle
    round-trip proves nothing about the formula.
    """

    def test_round_trips_against_required_surface_radius(self):
        for angle in (60.0, 90.0, 120.0):
            for mode in (form.INTERNAL, form.EXTERNAL):
                for pitch in (0.5, 1.25, 3.8):
                    r = form.required_surface_radius(
                        mode, 8.0, pitch, angle, 0.1, 0.1, 0.12)
                    got = form.achieved_diameter(
                        mode, pitch, angle, 0.1, 0.1, 0.12, r)
                    self.assertAlmostEqual(
                        got, 8.0, places=9,
                        msg="mode=%s angle=%s pitch=%s" % (mode, angle, pitch))

    def test_an_external_thread_is_its_own_shaft(self):
        self.assertAlmostEqual(
            form.achieved_diameter(form.EXTERNAL, 1.25, 90.0, 0.2, 0.2,
                                   0.12, 10.0),
            20.0, places=9)

    def test_an_internal_thread_is_larger_than_its_bore(self):
        got = form.achieved_diameter(form.INTERNAL, 1.25, 90.0, 0.2, 0.2,
                                     0.12, 5.0)
        self.assertGreater(got, 10.0)

    def test_the_gap_between_bore_and_thread_grows_with_a_shallower_V(self):
        """Depth is 1/tan(angle/2), so a 60 degree V reaches further than a
        120 degree one at the same pitch.  Checked across the pair rather
        than at one angle, for the reason in the class docstring."""
        sharp = form.achieved_diameter(form.INTERNAL, 1.25, 60.0, 0.1, 0.1,
                                       0.0, 5.0)
        blunt = form.achieved_diameter(form.INTERNAL, 1.25, 120.0, 0.1, 0.1,
                                       0.0, 5.0)
        self.assertGreater(sharp, blunt)

    def test_an_unknown_mode_raises(self):
        with self.assertRaises(form.ProfileError) as caught:
            form.achieved_diameter("Sideways", 1.25, 90.0, 0.2, 0.2, 0.12, 5.0)
        self.assertIn("Sideways", str(caught.exception))


class TestEffectiveSurfaceRadius(unittest.TestCase):
    """Diameter drives the size; the cutter reaches further to reach it.

    A die reduces the shaft as it cuts and a tap opens the bore, so exactly
    one direction is available in each mode. Every case is checked at 60 and
    90 degrees, because the depth term is 1/tan(angle/2) and a single angle
    cannot distinguish a right formula from a wrong one here either.
    """

    def test_external_can_cut_smaller_than_the_shaft(self):
        for angle in (60.0, 90.0):
            r = form.effective_surface_radius(
                form.EXTERNAL, 16.0, 2.0, angle, 0.4, 0.4, 0.12, 10.0)
            self.assertAlmostEqual(r, 8.0, places=9,
                                   msg="angle=%s" % angle)

    def test_external_larger_than_the_shaft_clamps_to_the_shaft(self):
        """Cannot add material, so fall back to anchoring on the blank.

        Clamping rather than raising is deliberate and was measured: an M8
        thread in a standard 6.8mm ISO tap drill wants a 6.52mm bore on the
        printed form, so the drill is legitimately too big and refusing
        outright failed every ordinary tapped hole in the suite. The caller
        reports the shortfall instead (api.diameter_note).
        """
        for angle in (60.0, 90.0):
            r = form.effective_surface_radius(
                form.EXTERNAL, 24.0, 2.0, angle, 0.4, 0.4, 0.12, 10.0)
            self.assertAlmostEqual(r, 10.0, places=9, msg="angle=%s" % angle)

    def test_internal_can_cut_larger_than_the_bore(self):
        for angle in (60.0, 90.0):
            r = form.effective_surface_radius(
                form.INTERNAL, 20.0, 2.5, angle, 0.4, 0.4, 0.12, 5.0)
            self.assertGreater(r, 5.0, "angle=%s" % angle)
            # and it is exactly the radius that yields the asked-for size
            self.assertAlmostEqual(
                form.achieved_diameter(form.INTERNAL, 2.5, angle, 0.4, 0.4,
                                       0.12, r),
                20.0, places=9)

    def test_internal_smaller_than_the_bore_clamps_to_the_bore(self):
        """The common real case: an ISO tap drill is bigger than the printed
        form wants, so this must degrade quietly rather than refuse."""
        for angle in (60.0, 90.0):
            r = form.effective_surface_radius(
                form.INTERNAL, 6.0, 1.0, angle, 0.2, 0.2, 0.12, 5.0)
            self.assertAlmostEqual(r, 5.0, places=9, msg="angle=%s" % angle)

    def test_a_standard_M8_tap_drill_is_not_refused(self):
        """The exact case that made refusing untenable: 6.8mm ISO drill."""
        r = form.effective_surface_radius(
            form.INTERNAL, 8.0, 1.25, 90.0, 0.225, 0.225, 0.12, 3.4)
        self.assertAlmostEqual(r, 3.4, places=9)

    def test_a_matching_blank_anchors_on_itself(self):
        """The ordinary case must cost nothing."""
        r = form.effective_surface_radius(
            form.EXTERNAL, 20.0, 2.5, 90.0, 0.4, 0.4, 0.12, 10.0)
        self.assertAlmostEqual(r, 10.0, places=9)

    def test_the_anchor_always_yields_the_requested_diameter(self):
        """Round-trip across the achievable direction in both modes."""
        for angle in (60.0, 90.0, 120.0):
            ext = form.effective_surface_radius(
                form.EXTERNAL, 12.0, 1.75, angle, 0.3, 0.3, 0.12, 10.0)
            self.assertAlmostEqual(
                form.achieved_diameter(form.EXTERNAL, 1.75, angle, 0.3, 0.3,
                                       0.12, ext),
                12.0, places=9, msg="external angle=%s" % angle)
            internal = form.effective_surface_radius(
                form.INTERNAL, 20.0, 1.75, angle, 0.3, 0.3, 0.12, 5.0)
            self.assertAlmostEqual(
                form.achieved_diameter(form.INTERNAL, 1.75, angle, 0.3, 0.3,
                                       0.12, internal),
                20.0, places=9, msg="internal angle=%s" % angle)


if __name__ == "__main__":
    unittest.main()
