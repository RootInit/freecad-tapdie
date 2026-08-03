import math
import unittest

import FreeCAD as App

from tapdie import cutter, form, measure


def build(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
          pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
          clearance=0.12, surface_radius=8.2597, height=15.2):
    pts = form.cutter_points(mode, form_name, diameter, pitch, angle,
                             root_land, crest_land, clearance, surface_radius,
                             1.0)
    return cutter.build(pts, pitch, height)


class TestCutterSolid(unittest.TestCase):
    def test_produces_a_single_valid_solid(self):
        sh = build()
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)

    def test_shape_outlives_the_scratch_document(self):
        before = len(App.listDocuments())
        sh = build()
        self.assertGreater(sh.Volume, 0.0)
        self.assertEqual(len(App.listDocuments()), before,
                         "scratch document was left open")

    def test_flank_angle_is_the_requested_half_angle(self):
        # This is the check that a validity test cannot make.  MakePipeShell
        # returned valid single solids here while distorting flanks to 38-60
        # degrees, so the angle must be measured, not assumed.
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["flank_angles"], "no flanks found in section")
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 45.0, places=2)

    def test_tip_land_is_the_requested_width(self):
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        tips = [w for r, w in prof["lands"] if abs(r - 10.1297) < 0.01]
        self.assertTrue(tips, "no tip land found; lands=%s" % prof["lands"])
        for w in tips:
            self.assertAlmostEqual(w, 0.08, places=3)

    def test_far_land_is_pitch_minus_crest_land(self):
        # The cutter's parallel section has half-width hw = (pitch -
        # crest_land) / 2, so the land at the cutter's `far` radius (the
        # overrun band, r = surface_radius - overrun = 8.2597 - 1.0) is
        # exactly pitch - crest_land wide: 3.8 - 0.08 = 3.72.
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        far = [w for r, w in prof["lands"] if abs(r - 7.2597) < 0.01]
        self.assertTrue(far, "no far land found; lands=%s" % prof["lands"])
        for w in far:
            self.assertAlmostEqual(w, 3.8 - 0.08, places=3)

    def test_sixty_degree_form_gives_thirty_degree_flanks(self):
        sh = build(form_name=form.ISO, angle=60.0, pitch=1.25,
                   root_land=0.15625, crest_land=0.3125, diameter=8.0,
                   surface_radius=3.3234, height=8.0)
        prof = measure.profile(sh, 2.0, 6.0)
        self.assertTrue(prof["flank_angles"])
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 30.0, places=2)
        # ISO needs the crest_land assertion too: far radius = surface_radius
        # (3.3234) - overrun (1.0) = 2.3234, width = pitch - crest_land =
        # 1.25 - 0.3125 = 0.9375.
        far = [w for r, w in prof["lands"] if abs(r - 2.3234) < 0.01]
        self.assertTrue(far, "no far land found; lands=%s" % prof["lands"])
        for w in far:
            self.assertAlmostEqual(w, 1.25 - 0.3125, places=3)

    def test_shallow_lead_angle_survives(self):
        # Fine pitch on a large diameter -- the case that broke MakePipeShell.
        sh = build(pitch=1.0, root_land=0.05, crest_land=0.05,
                   surface_radius=9.3, height=15.0)
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)
        prof = measure.profile(sh, 3.0, 12.0)
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 45.0, places=2)

    def test_external_mode_builds(self):
        # Validity checks are a precondition, not proof; measure the shape
        # the same way the internal-mode tests do, not just isValid().
        sh = build(mode=form.EXTERNAL, surface_radius=10.0, diameter=20.0)
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["flank_angles"], "no flanks found in section")
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 45.0, places=2)
        # tip land at r = surface_radius - clearance*sec = 7.9703, width =
        # root_land = 0.08; far land at r = surface_radius + overrun = 11.0,
        # width = pitch - crest_land = 3.72.
        tips = [w for r, w in prof["lands"] if abs(r - 7.9703) < 0.01]
        self.assertTrue(tips, "no tip land found; lands=%s" % prof["lands"])
        for w in tips:
            self.assertAlmostEqual(w, 0.08, places=3)
        far = [w for r, w in prof["lands"] if abs(r - 11.0) < 0.01]
        self.assertTrue(far, "no far land found; lands=%s" % prof["lands"])
        for w in far:
            self.assertAlmostEqual(w, 3.8 - 0.08, places=3)

    def test_hundred_degree_form_gives_fifty_degree_flanks(self):
        sh = build(form_name=form.CUSTOM, angle=100.0)
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["flank_angles"])
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 50.0, places=2)


class TestCutterErrors(unittest.TestCase):
    """cutter.CutterError is declared interface; every guard must be hit.

    Each assertion checks a distinctive message substring, not just the
    exception type -- a type-only assertion would pass on a neighbouring
    guard firing for the wrong reason.
    """

    def test_too_few_points_is_rejected(self):
        with self.assertRaises(cutter.CutterError) as ctx:
            cutter.build([(1.0, 0.0), (2.0, 1.0)], 1.0, 1.0)
        self.assertIn("at least 3 corners", str(ctx.exception))

    def test_nonpositive_pitch_is_rejected(self):
        pts = [(1.0, 0.0), (2.0, 1.0), (2.0, -1.0)]
        with self.assertRaises(cutter.CutterError) as ctx:
            cutter.build(pts, 0.0, 1.0)
        self.assertIn("must both be positive", str(ctx.exception))

    def test_nonpositive_height_is_rejected(self):
        pts = [(1.0, 0.0), (2.0, 1.0), (2.0, -1.0)]
        with self.assertRaises(cutter.CutterError) as ctx:
            cutter.build(pts, 1.0, 0.0)
        self.assertIn("must both be positive", str(ctx.exception))

    def test_self_intersecting_profile_raises_and_cleans_up(self):
        """A bowtie profile -- two crossing edges -- sweeps into an invalid
        solid.  This is the only test that exercises the isValid() / solid-
        count / volume guards after recompute, and it also confirms the
        scratch document is closed even on this failure path.
        """
        bowtie = [(5.0, 0.0), (6.0, 1.0), (6.0, 0.0), (5.0, 1.0)]
        before = len(App.listDocuments())
        with self.assertRaises(cutter.CutterError) as ctx:
            cutter.build(bowtie, 2.0, 5.0)
        self.assertIn("not a valid solid", str(ctx.exception))
        after = len(App.listDocuments())
        self.assertEqual(after, before,
                         "scratch document was left open after failure")


class TestMeasureIsHonest(unittest.TestCase):
    def test_section_finds_a_known_cone_flank(self):
        """Control: a cone of known slope must measure at that slope.

        If this fails the MEASUREMENT is broken, not the cutter, and every
        other assertion in this file is worthless.

        The cone is truncated (top radius 2.0, not 0.0) for two reasons: a
        full cone's flank runs to r=0 and is dropped by the r_min guard, and
        a 45 degree cone would read the same under either atan2 argument
        order, so it could not catch the convention bug this test now guards.
        """
        import Part
        cone = Part.makeCone(10.0, 2.0, 4.0)
        prof = measure.profile(cone, -1.0, 5.0)
        self.assertTrue(prof["flank_angles"], "no flank found in the section")
        expected = math.degrees(math.atan2(4.0, 8.0))     # 26.565 degrees
        self.assertAlmostEqual(prof["flank_angles"][0], expected, places=2)


if __name__ == "__main__":
    unittest.main()
