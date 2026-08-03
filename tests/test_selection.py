import unittest

import FreeCAD as App
import Part

from tapdie import form, selection


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("seltest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _add(self, shape):
        obj = self.doc.addObject("Part::Feature", "S")
        obj.Shape = shape
        self.doc.recompute()
        return obj

    def _cylindrical_face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - radius) < 1e-6:
                return "Face%d" % (i + 1)
        raise AssertionError("no cylindrical face of radius %.3f" % radius)

    def _circular_edge(self, obj):
        for i, e in enumerate(obj.Shape.Edges):
            if hasattr(e.Curve, "Radius"):
                return "Edge%d" % (i + 1)
        raise AssertionError("no circular edge")

    def test_shaft_outer_face_is_external(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertEqual(circle.mode, form.EXTERNAL)
        self.assertAlmostEqual(circle.radius, 10.0, places=6)

    def test_bore_inner_face_is_internal(self):
        outer = Part.makeCylinder(20.0, 30.0)
        bore = Part.makeCylinder(8.0, 30.0)
        obj = self._add(outer.cut(bore))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 8.0))
        self.assertEqual(circle.mode, form.INTERNAL)
        self.assertAlmostEqual(circle.radius, 8.0, places=6)

    def test_axis_is_unit_length(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertAlmostEqual(circle.axis.Length, 1.0, places=9)

    def test_face_length_becomes_the_default_length(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertAlmostEqual(circle.length, 30.0, places=3)

    def test_circular_edge_resolves(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        name = None
        for i, e in enumerate(obj.Shape.Edges):
            if hasattr(e.Curve, "Radius"):
                name = "Edge%d" % (i + 1)
                break
        self.assertIsNotNone(name)
        circle = selection.resolve(obj, name)
        self.assertAlmostEqual(circle.radius, 10.0, places=6)

    def test_planar_face_is_rejected(self):
        obj = self._add(Part.makeBox(10, 10, 10))
        with self.assertRaisesRegex(selection.SelectionError, "cylindrical"):
            selection.resolve(obj, "Face1")

    def test_counterbore_face_centre_lies_within_its_true_range(self):
        # A block cut by two coaxial cylinders sharing origin (0, 0, 0): a
        # shallow, larger-radius counterbore (z 0..15, r 15) and a deep,
        # smaller-radius through-hole (z 0..40, r 8).  Because the counterbore
        # already removed material for z 0..15, the r=8 wall only exists for
        # z 15..40 -- its underlying Part.Cylinder surface frame is still
        # centred at the shared origin (0, 0, 0), fifteen millimetres outside
        # its own face.  This is the fixture that catches both Criticals: a
        # wrong centre feeds a wrong probe point, which turns an ordinary
        # unambiguous bore into a false "ambiguous".
        outer = Part.makeCylinder(20.0, 50.0)
        counterbore = Part.makeCylinder(15.0, 15.0)
        through = Part.makeCylinder(8.0, 40.0)
        obj = self._add(outer.cut(counterbore).cut(through))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 8.0))
        self.assertEqual(circle.mode, form.INTERNAL)
        self.assertGreaterEqual(circle.centre.z, 15.0 - 1e-6)
        self.assertLessEqual(circle.centre.z, 40.0 + 1e-6)

    def test_face_length_survives_a_tilted_axis(self):
        cyl = Part.makeCylinder(10.0, 50.0)
        cyl.Placement = App.Placement(
            App.Vector(0, 0, 0), App.Rotation(App.Vector(0, 1, 0), 30))
        obj = self._add(cyl)
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertAlmostEqual(circle.length, 50.0, places=3)

    def test_edge_length_survives_a_tilted_axis(self):
        cyl = Part.makeCylinder(10.0, 50.0)
        cyl.Placement = App.Placement(
            App.Vector(0, 0, 0), App.Rotation(App.Vector(0, 1, 0), 30))
        obj = self._add(cyl)
        circle = selection.resolve(obj, self._circular_edge(obj))
        self.assertAlmostEqual(circle.length, 50.0, places=3)

    def test_wall_thinner_than_every_probe_step_is_ambiguous(self):
        # Wall thickness 0.01mm is smaller than the smallest probe offset
        # tried (radius 8 * PROBE_FRACTIONS[-1] = 0.016mm), so every fraction
        # probes past the opposite surface on both sides: False/False every
        # time, exhausting the retry loop.
        outer = Part.makeCylinder(8.0, 30.0)
        inner = Part.makeCylinder(7.99, 30.0)
        obj = self._add(outer.cut(inner))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 8.0))
        self.assertIsNone(circle.mode)

    def test_out_of_range_face_name_is_rejected(self):
        obj = self._add(Part.makeBox(10, 10, 10))
        with self.assertRaisesRegex(selection.SelectionError, "Face99"):
            selection.resolve(obj, "Face99")

    def test_out_of_range_edge_name_is_rejected(self):
        obj = self._add(Part.makeBox(10, 10, 10))
        with self.assertRaisesRegex(selection.SelectionError, "Edge99"):
            selection.resolve(obj, "Edge99")


if __name__ == "__main__":
    unittest.main()
