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

    def test_sixty_degree_form_gives_thirty_degree_flanks(self):
        sh = build(form_name=form.ISO, angle=60.0, pitch=1.25,
                   root_land=0.15625, crest_land=0.3125, diameter=8.0,
                   surface_radius=3.3234, height=8.0)
        prof = measure.profile(sh, 2.0, 6.0)
        self.assertTrue(prof["flank_angles"])
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 30.0, places=2)

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
        sh = build(mode=form.EXTERNAL, surface_radius=10.0, diameter=20.0)
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)

    def test_hundred_degree_form_gives_fifty_degree_flanks(self):
        sh = build(form_name=form.CUSTOM, angle=100.0)
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["flank_angles"])
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 50.0, places=2)


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
