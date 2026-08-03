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
        with self.assertRaises(form.ProfileError):
            self.points(root_land=2.0, crest_land=2.0)

    def test_zero_root_land_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            self.points(root_land=0.0)

    def test_zero_crest_land_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            self.points(crest_land=0.0)

    def test_shoulder_short_of_the_bore_is_rejected(self):
        # A bore far larger than the thread leaves the cutter unable to reach.
        with self.assertRaises(form.ProfileError):
            self.points(surface_radius=15.0)


if __name__ == "__main__":
    unittest.main()
