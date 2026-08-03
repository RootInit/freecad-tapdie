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
        with self.assertRaises(selection.SelectionError):
            selection.resolve(obj, "Face1")


if __name__ == "__main__":
    unittest.main()
