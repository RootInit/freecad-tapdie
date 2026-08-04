import math
import unittest

import FreeCAD as App

from tapdie import cutter, form, measure


# Clearance defaults to 0 here purely so the radii below can be written
# against surface_radius directly.  Clearance no longer touches the lands at
# all -- it shifts the whole profile radially (form.crest_radius) -- so a
# nonzero value would change only where the profile sits, not its shape.
# TestClearanceOnTheSolid exercises that separately.
def build(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
          pitch=3.8, angle=90.0, root_land=0.08, crest_land=0.08,
          clearance=0.0, surface_radius=8.2597, height=15.2):
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
        # The profile is anchored on the SURFACE, so the tip sits one cut
        # depth outside it: 8.2597 + cut_depth(3.8, 90, 0.08, 0.08) = 10.0797.
        sh = build()
        tip_r = 8.2597 + form.cut_depth(3.8, 90.0, 0.08, 0.08)
        self.assertAlmostEqual(tip_r, 10.0797, places=4)
        prof = measure.profile(sh, 3.0, 12.0)
        tips = [w for r, w in prof["lands"] if abs(r - tip_r) < 0.01]
        self.assertTrue(tips, "no tip land found; lands=%s" % prof["lands"])
        for w in tips:
            self.assertAlmostEqual(w, 0.08, places=3)

    def test_the_cutters_own_radial_faces_are_only_its_overrun(self):
        """The CUTTER is allowed radial faces; the cut PART is not.

        The profile's (shoulder -> far) segment runs at constant axial offset
        across the parallel section, so the swept cutter carries a flat
        annulus of exactly `overrun` at each end of every turn. That face is
        what forms the thread's crest land, and it lies outside the finished
        part entirely -- which is why "no shelves" is asserted on the cut
        solid (tests/test_profile_shape.py) and not here. Pin the width so a
        shelf of any OTHER size still shows up.
        """
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["shelves"], "expected the overrun faces")
        for _z, width in prof["shelves"]:
            self.assertAlmostEqual(width, 1.0, places=6)   # overrun

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
        # tip land one cut depth INSIDE the surface: 10.0 - 1.82 = 8.18,
        # width = root_land = 0.08; far land at r = surface_radius + overrun
        # = 11.0, width = pitch - crest_land = 3.72.
        tip_r = 10.0 - form.cut_depth(3.8, 90.0, 0.08, 0.08)
        self.assertAlmostEqual(tip_r, 8.18, places=4)
        tips = [w for r, w in prof["lands"] if abs(r - tip_r) < 0.01]
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


class TestClearanceOnTheSolid(unittest.TestCase):
    """Clearance measured off the built solid, not off the arithmetic."""

    KW = dict(pitch=3.8, angle=90.0, root_land=0.4, crest_land=0.5,
              surface_radius=8.2597, height=15.2)

    def _tip_land(self, sh, tip_r):
        prof = measure.profile(sh, 3.0, 12.0)
        bands = [w for r, w in prof["lands"] if abs(r - tip_r) < 0.01]
        self.assertTrue(bands, "no tip land at r=%.4f; lands=%s"
                        % (tip_r, prof["lands"]))
        return bands[0], prof

    def test_lands_survive_clearance_unchanged(self):
        """Taken radially, clearance costs the lands nothing.

        The axial alternative ate 2*c*sec(45) = 0.34mm of crest land for a
        0.12 gap, which no fine pitch could afford.
        """
        for c in (0.0, 0.12, 0.3):
            depth = form.cut_depth(3.8, 90.0, 0.4, 0.5)
            tip_r = form.crest_radius(form.INTERNAL, 8.2597, c, 90.0) + depth
            sh = build(clearance=c, **self.KW)
            width, prof = self._tip_land(sh, tip_r)
            self.assertAlmostEqual(width, 0.4, places=3,
                                   msg="root land at clearance %.2f" % c)

    def test_shifts_the_profile_radially_by_c_over_sin(self):
        depth = form.cut_depth(3.8, 90.0, 0.4, 0.5)
        tips = {}
        for c in (0.0, 0.12):
            sh = build(clearance=c, **self.KW)
            prof = measure.profile(sh, 3.0, 12.0)
            tips[c] = prof["r_max"]
        self.assertAlmostEqual(tips[0.12] - tips[0.0],
                               form.radial_offset(0.12, 90.0), places=3)

    def test_flank_angle_survives_clearance(self):
        for c in (0.0, 0.12, 0.3):
            sh = build(clearance=c, **self.KW)
            prof = measure.profile(sh, 3.0, 12.0)
            self.assertTrue(prof["flank_angles"])
            for a in prof["flank_angles"]:
                self.assertAlmostEqual(
                    a, 45.0, places=2,
                    msg="clearance %.2f rotated a flank" % c)

    def test_clearance_adds_no_radial_face_beyond_the_parallel_section(self):
        # The only radial faces a cutter may carry are the two ends of its
        # parallel section. That section spans from the RELIEVED surface
        # (where the shoulder sits) out past the ORIGINAL one (where `far`
        # sits, so the cutter still clears an unrelieved blank), so its
        # width is overrun + radial_offset, not overrun alone. Clearance
        # must not introduce a face of any other width.
        for c in (0.0, 0.06, 0.12, 0.3):
            expected = 1.0 + form.radial_offset(c, 90.0)   # overrun = 1.0
            sh = build(clearance=c, **self.KW)
            prof = measure.profile(sh, 3.0, 12.0)
            self.assertTrue(prof["shelves"], "expected the parallel section")
            for _z, width in prof["shelves"]:
                self.assertAlmostEqual(
                    width, expected, places=6,
                    msg="clearance %.2f produced a %.4fmm radial face, "
                        "expected %.4f" % (c, width, expected))


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
