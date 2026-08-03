import unittest

import FreeCAD as App
import Part

from tapdie import feature, form


class TestThreadCutterFeature(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("feattest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _cutter(self, **props):
        obj = feature.make_cutter(self.doc)
        obj.Mode = props.pop("Mode", form.INTERNAL)
        obj.Diameter = props.pop("Diameter", 20.0)
        obj.Pitch = props.pop("Pitch", 3.8)
        obj.RootLand = props.pop("RootLand", 0.08)
        obj.CrestLand = props.pop("CrestLand", 0.08)
        obj.Clearance = props.pop("Clearance", 0.12)
        obj.SurfaceRadius = props.pop("SurfaceRadius", 8.2597)
        obj.Length = props.pop("Length", 15.2)
        for k, v in props.items():
            setattr(obj, k, v)
        self.doc.recompute()
        return obj

    def test_recomputes_to_a_valid_solid(self):
        obj = self._cutter()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)

    def test_editing_pitch_changes_the_shape(self):
        obj = self._cutter()
        before = obj.Shape.Volume
        obj.Pitch = 2.0
        obj.RootLand = 0.05
        obj.CrestLand = 0.05
        self.doc.recompute()
        self.assertNotAlmostEqual(obj.Shape.Volume, before, places=3)

    def test_impossible_parameters_leave_the_feature_in_error(self):
        obj = self._cutter()
        obj.CrestLand = 5.0       # leaves no flank within the pitch
        self.doc.recompute()
        self.assertTrue("Invalid" in obj.State or "Touched" in obj.State,
                        "expected an error state, got %s" % obj.State)

    def test_reversed_runs_the_thread_the_other_way(self):
        obj = self._cutter()
        forward_box = obj.Shape.optimalBoundingBox()
        forward_volume = obj.Shape.Volume
        obj.Reversed = True
        self.doc.recompute()
        back_box = obj.Shape.optimalBoundingBox()
        # A proper rotation moves the solid without resizing it.
        self.assertAlmostEqual(obj.Shape.Volume, forward_volume, places=6)
        self.assertLess(back_box.ZMax, forward_box.ZMax - 1.0)

    def test_preset_locks_the_angle(self):
        obj = self._cutter(ThreadForm=form.ISO, Pitch=1.25, Diameter=8.0,
                           SurfaceRadius=3.3234, Length=8.0)
        self.assertAlmostEqual(obj.Angle.Value, 60.0, places=6)
        self.assertTrue(obj.getEditorMode("Angle"))

    def test_custom_form_unlocks_the_angle(self):
        obj = self._cutter(ThreadForm=form.CUSTOM)
        self.assertEqual(obj.getEditorMode("Angle"), [])


if __name__ == "__main__":
    unittest.main()
