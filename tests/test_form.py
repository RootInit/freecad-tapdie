import math
import unittest

from tapdie import form


class TestDepth(unittest.TestCase):
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


class TestCutterPoints(unittest.TestCase):
    """Reproduces the printed_threads nut cutter, which is measured and known."""

    KW = dict(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
              pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
              clearance=0.12, surface_radius=8.2597, overrun=1.0)

    def points(self, **over):
        kw = dict(self.KW)
        kw.update(over)
        return form.cutter_points(
            kw["mode"], kw["form_name"], kw["diameter"], kw["pitch"],
            kw["angle"], kw["root_land"], kw["crest_land"], kw["clearance"],
            kw["surface_radius"], kw["overrun"])

    def test_returns_six_corners(self):
        self.assertEqual(len(self.points()), 6)

    def test_tip_radius_matches_measured_geometry(self):
        # printed_threads measures the nut root land at r = 10.1297.
        self.assertAlmostEqual(self.points()[0][0], 10.1297, places=3)

    def test_root_land_is_the_requested_width(self):
        pts = self.points()
        self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.08, places=6)

    def test_parallel_section_is_pitch_minus_crest_land(self):
        pts = self.points()
        self.assertAlmostEqual(pts[2][1] - pts[3][1], 3.8 - 0.08, places=6)

    def test_lands_are_independent(self):
        """ISO needs P/8 at the root and P/4 at the crest simultaneously."""
        pts = self.points(pitch=1.25, root_land=0.15625, crest_land=0.3125,
                          angle=60.0, form_name=form.ISO, diameter=8.0,
                          surface_radius=3.3234)
        self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.15625, places=6)
        self.assertAlmostEqual(pts[2][1] - pts[3][1], 1.25 - 0.3125, places=6)

    def test_flank_is_at_the_half_angle(self):
        pts = self.points()
        tip, shoulder = pts[0], pts[1]
        dr = abs(shoulder[0] - tip[0])
        dz = abs(shoulder[1] - tip[1])
        self.assertAlmostEqual(math.degrees(math.atan2(dr, dz)), 45.0, places=4)

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

    def test_shoulder_short_of_the_bore_is_rejected(self):
        # A bore far larger than the thread leaves the cutter unable to reach.
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(surface_radius=15.0)
        self.assertIn("cannot reach the bore", str(ctx.exception))


class TestCriticalValidation(unittest.TestCase):
    """Test input validation for critical error modes."""

    KW = dict(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
              pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
              clearance=0.12, surface_radius=8.2597, overrun=1.0)

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

    def test_overrun_larger_than_shoulder_is_rejected_internal(self):
        """An overrun larger than shoulder radius folds far through the axis."""
        # With default params, shoulder ≈ 8.31, surface_radius = 8.2597.
        # far = min(shoulder, surface_radius) - overrun = 8.2597 - overrun
        # overrun = 10 makes far = -1.74, which should be rejected.
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(overrun=10.0)
        self.assertIn("reaches through the axis", str(ctx.exception))

    def test_external_shoulder_overshoots_surface_is_rejected(self):
        """EXTERNAL where shoulder is larger than surface radius."""
        # With a small surface_radius, the shoulder will overshoot.
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode=form.EXTERNAL, diameter=20.0, pitch=3.8,
                        surface_radius=8.0)
        self.assertIn("overshoots the surface", str(ctx.exception))

    def test_external_thread_deeper_than_shaft_is_rejected(self):
        """EXTERNAL where thread depth exceeds shaft radius, making tip <= 0."""
        # Parameters verified to hit the "tip <= 0" guard specifically:
        # depth=15.0, apex=-10.1697, tip=-10.1297 (< 0, target)
        # shoulder=4.7903 (< surface_radius=5.0, so shoulder guard stays quiet)
        with self.assertRaises(form.ProfileError) as ctx:
            self.points(mode=form.EXTERNAL, form_name=form.PRINTED, diameter=10.0,
                        pitch=30.0, angle=90.0, surface_radius=5.0)
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


class TestDepthValidation(unittest.TestCase):
    """Test validation in depth() function."""

    def test_depth_invalid_mode(self):
        """depth() validates mode enum."""
        with self.assertRaises(form.ProfileError) as ctx:
            form.depth(form.PRINTED, 3.8, 90.0, "Bogus")
        self.assertIn("is not", str(ctx.exception))

    def test_depth_invalid_form_name(self):
        """depth() validates form_name enum."""
        with self.assertRaises(form.ProfileError) as ctx:
            form.depth("Bogus", 3.8, 90.0, form.INTERNAL)
        self.assertIn("is not one of", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
