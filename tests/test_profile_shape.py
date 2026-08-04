"""The shelf regression guard, measured on the CUT SOLID.

Everything here builds a real blank, threads it through the public api, and
sections the result.  Nothing checks the arithmetic that positioned the
cutter -- that is what let the defect through the first time: the profile
maths and the solid agreed with each other and both were wrong.

The defect: the cutter's flank stopped short of the surface being threaded
and its parallel section covered the difference, leaving a flat annulus
normal to the axis between every pair of turns instead of a flank running to
the crest.  Measured 0.3697mm of it on a nominal M8x1.25 shaft, in both
modes, at every pitch and every form -- worst on ISO, where it reached
0.96mm at a 3.8 pitch.
"""

import unittest

import FreeCAD as App

from tapdie import api, form, measure

SHAFT_LEN = 30.0


def _blank(doc, mode, surface_radius):
    """A plain shaft or a plain bored block, and the face to thread."""
    if mode == form.EXTERNAL:
        base = doc.addObject("Part::Cylinder", "Shaft")
        base.Radius = surface_radius
        base.Height = SHAFT_LEN
    else:
        outer = doc.addObject("Part::Cylinder", "Outer")
        outer.Radius = surface_radius * 2.0 + 2.0
        outer.Height = SHAFT_LEN
        bore = doc.addObject("Part::Cylinder", "Bore")
        bore.Radius = surface_radius
        bore.Height = SHAFT_LEN + 2.0
        bore.Placement.Base = App.Vector(0, 0, -1)
        base = doc.addObject("Part::Cut", "Blank")
        base.Base, base.Tool = outer, bore
    doc.recompute()

    for i, face in enumerate(base.Shape.Faces):
        surface = face.Surface
        if (hasattr(surface, "Radius")
                and abs(surface.Radius - surface_radius) < 1e-6):
            return base, "Face%d" % (i + 1)
    raise AssertionError("no cylindrical face at r=%.4f" % surface_radius)


class ShelfTest(unittest.TestCase):
    """No flat annulus may stand between a crest and a flank."""

    def _section(self, mode, form_name, pitch, surface_radius, **over):
        doc = App.newDocument("shelf_probe")
        try:
            base, sub = _blank(doc, mode, surface_radius)
            # Length scales with pitch so the measurement window stays more
            # than a pitch wide once the chamfers are excluded.
            params = {"Mode": mode, "ThreadForm": form_name,
                      "Pitch": pitch, "Length": max(12.0, 6.0 * pitch)}
            params.update(over)
            cutter_obj, cut = api.create_thread(doc, base, sub, params)
            doc.recompute()

            shape = cut.Shape.copy()
            shape.Placement = App.Placement()

            # The window must sit strictly INSIDE the plain thread, because
            # two things at the ends of the run are legitimately radial and
            # are not shelves: the 45 degree lead-in chamfers, and the step
            # where the crest relief meets full diameter. A window merely
            # centred on the run overflowed both and reported them as
            # shelves.
            mid = SHAFT_LEN / 2.0
            half = cutter_obj.Length.Value / 2.0
            chamfer = (form.cut_depth(pitch, cutter_obj.Angle.Value,
                                      cutter_obj.RootLand.Value,
                                      cutter_obj.CrestLand.Value)
                       + form.radial_offset(cutter_obj.Clearance.Value,
                                            cutter_obj.Angle.Value))
            reach = half - chamfer - 0.2
            self.assertGreater(
                reach, pitch,
                "window shorter than a pitch (Length=%.2f, chamfer=%.3f): "
                "widen Length or the test proves nothing"
                % (cutter_obj.Length.Value, chamfer))
            return measure.profile(shape, mid - reach, mid + reach)
        finally:
            App.closeDocument(doc.Name)

    def _assert_no_shelf(self, prof, label):
        self.assertTrue(prof["lands"], "%s: sectioned nothing" % label)
        self.assertFalse(
            prof["shelves"],
            "%s: %d flat annular shelves between turns, widest %.4fmm -- "
            "the cutter's flank is not reaching the surface"
            % (label, len(prof["shelves"]),
               max(w for _, w in prof["shelves"]) if prof["shelves"] else 0.0))

    def test_external_printed_has_no_shelf(self):
        prof = self._section(form.EXTERNAL, form.PRINTED, 1.25, 4.0,
                             Diameter=8.0)
        self._assert_no_shelf(prof, "external printed M8x1.25")

    def test_internal_printed_has_no_shelf(self):
        prof = self._section(form.INTERNAL, form.PRINTED, 1.25, 3.375,
                             Diameter=8.0)
        self._assert_no_shelf(prof, "internal printed M8x1.25")

    def test_external_iso_has_no_shelf(self):
        prof = self._section(form.EXTERNAL, form.ISO, 1.25, 4.0,
                             Diameter=8.0)
        self._assert_no_shelf(prof, "external ISO M8x1.25")

    def test_internal_iso_has_no_shelf(self):
        prof = self._section(form.INTERNAL, form.ISO, 1.25, 3.375,
                             Diameter=8.0)
        self._assert_no_shelf(prof, "internal ISO M8x1.25")

    def test_no_shelf_at_a_coarse_pitch(self):
        # 3.8 is printed_threads' pitch, and the pitch at which the ISO
        # shelf was worst (0.96mm).
        for form_name in (form.PRINTED, form.ISO):
            prof = self._section(form.EXTERNAL, form_name, 3.8, 10.0,
                                 Diameter=20.0)
            self._assert_no_shelf(prof, "external %s P3.8" % form_name)

    def test_diameter_far_off_the_blank_still_leaves_no_shelf(self):
        """A wrong Diameter must not be able to reintroduce the shelf.

        Anchoring on Diameter is what produced the shelf, so the case where
        Diameter and the real surface disagree most is the one that has to
        stay clean. The thread comes out the wrong SIZE here -- that is
        expected and is what required_surface_radius() reports -- but it must
        still be the right SHAPE.
        """
        for diameter in (5.0, 8.0, 16.0):
            prof = self._section(form.EXTERNAL, form.PRINTED, 1.25, 4.0,
                                 Diameter=diameter)
            self._assert_no_shelf(prof, "external Diameter=%.1f" % diameter)


class ProfileIdentityTest(unittest.TestCase):
    """The cut solid must obey pitch = crest + root + 2*depth*tan."""

    def test_measured_lands_and_depth_close_the_pitch(self):
        doc = App.newDocument("identity_probe")
        try:
            base, sub = _blank(doc, form.EXTERNAL, 10.0)
            cutter_obj, cut = api.create_thread(doc, base, sub, {
                "Mode": form.EXTERNAL, "ThreadForm": form.PRINTED,
                "Diameter": 20.0, "Pitch": 3.8, "Length": 12.0})
            doc.recompute()

            shape = cut.Shape.copy()
            shape.Placement = App.Placement()
            mid = SHAFT_LEN / 2.0
            prof = measure.profile(shape, mid - 7.6, mid + 7.6)

            radii = sorted({r for r, _ in prof["lands"]})
            self.assertEqual(len(radii), 2, "expected a crest and a root")
            root_r, crest_r = radii[0], radii[1]
            widths = {}
            for r, w in prof["lands"]:
                widths.setdefault(r, w)

            # Clearance is radial, so the lands come out at exactly the
            # widths the object carries -- no correction term at all.
            self.assertAlmostEqual(widths[crest_r],
                                   cutter_obj.CrestLand.Value, places=3)
            self.assertAlmostEqual(widths[root_r],
                                   cutter_obj.RootLand.Value, places=3)

            # And the identity itself, read entirely off the solid.
            import math
            tan = math.tan(math.radians(cutter_obj.Angle.Value / 2.0))
            self.assertAlmostEqual(
                widths[crest_r] + widths[root_r]
                + 2.0 * (crest_r - root_r) * tan,
                3.8, places=3)
        finally:
            App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
