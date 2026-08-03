import math
import unittest

import FreeCAD as App
import Part

from tapdie import feature, form, selection


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
        self.assertIn("leaves no flank", obj.getStatusString())

    def test_reversed_keeps_the_sweep_centred_on_the_anchor(self):
        """Reversed flips the sweep direction, not where it's centred.

        Renamed and re-asserted for Task 7's offset fix: the anchor
        (LocalPlacement/AttachedTo, or the origin when unattached) is a
        MIDPOINT, so both the forward and reversed sweep must be centred on
        it symmetrically. The previous version of this test asserted
        `back_box.ZMax < forward_box.ZMax - 1.0`, which was only true
        because of the one-pitch offset this task replaced -- with a real
        AttachedTo anchor at a part's midpoint, that shift walked the
        reversed cutter off the part entirely (see
        test_reversed_stays_on_the_part in TestCreateThread).
        """
        obj = self._cutter()
        forward_box = obj.Shape.optimalBoundingBox()
        forward_volume = obj.Shape.Volume
        obj.Reversed = True
        self.doc.recompute()
        back_box = obj.Shape.optimalBoundingBox()
        # A proper rotation moves the solid without resizing it, and the
        # centred offset keeps both sweeps spanning the same envelope.
        self.assertAlmostEqual(obj.Shape.Volume, forward_volume, places=6)
        self.assertAlmostEqual(back_box.ZMin, forward_box.ZMin, places=3)
        self.assertAlmostEqual(back_box.ZMax, forward_box.ZMax, places=3)
        # Confirm Reversed actually took the 180-about-X branch, not a no-op.
        self.assertAlmostEqual(obj.Placement.Rotation.Angle, math.pi, places=6)

    def test_preset_locks_the_angle(self):
        obj = self._cutter(ThreadForm=form.ISO, Pitch=1.25, Diameter=8.0,
                           SurfaceRadius=3.3234, Length=8.0)
        self.assertAlmostEqual(obj.Angle.Value, 60.0, places=6)
        self.assertTrue(obj.getEditorMode("Angle"))

    def test_custom_form_unlocks_the_angle(self):
        obj = self._cutter(ThreadForm=form.CUSTOM)
        self.assertEqual(obj.getEditorMode("Angle"), [])

    def test_fresh_cutter_locks_the_angle_without_any_edits(self):
        # ThreadForm defaults to a preset (Printed 90), so the lock must be
        # in effect from construction -- not only once something reactively
        # triggers onChanged.
        obj = feature.make_cutter(self.doc)
        self.assertTrue(obj.getEditorMode("Angle"))


from tapdie import api


class TestCreateThread(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("apitest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _bored_block(self, bore_radius=3.4, height=20.0):
        outer = Part.makeCylinder(10.0, height)
        bore = Part.makeCylinder(bore_radius, height)
        obj = self.doc.addObject("Part::Feature", "Part")
        obj.Shape = outer.cut(bore)
        self.doc.recompute()
        return obj

    def _bore_face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - radius) < 1e-6:
                return "Face%d" % (i + 1)
        raise AssertionError("no face of radius %.3f" % radius)

    def test_creates_a_cut_of_base_and_cutter(self):
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        self.assertEqual(cut_obj.TypeId, "Part::Cut")
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)

    def test_the_thread_removes_material(self):
        base = self._bored_block()
        before = base.Shape.Volume
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        self.assertLess(cut_obj.Shape.Volume, before - 1e-6)

    def test_moving_the_base_keeps_the_thread(self):
        """Regression: Part::Cut does not bind Base and Tool placements.

        Without an explicit binding the Cut recomputes to the full uncut
        volume and reports success -- the thread silently vanishes.
        """
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        threaded = cut_obj.Shape.Volume

        base.Placement = App.Placement(App.Vector(50, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertAlmostEqual(cut_obj.Shape.Volume, threaded, places=3)

    def test_rotating_the_base_keeps_the_thread(self):
        """Rotation is why the binding composes placements.

        An expression on Placement.Base.x would translate the cutter but never
        turn it, so a rotated part would come out threaded off-axis.
        """
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        threaded = cut_obj.Shape.Volume

        base.Placement = App.Placement(
            App.Vector(10, 5, 0),
            App.Rotation(App.Vector(1, 1, 0), 37.0))
        self.doc.recompute()
        # delta, not places=3: Task 7's offset fix (see feature.py) centres
        # the cutter's pitch overrun to deliberately graze both flat end
        # faces (by design -- that overrun is what stops a mating crest
        # jamming on a plain collar). A generic 3D rotation makes that
        # near-boundary intersection slightly tolerance-sensitive inside
        # the OCC boolean kernel: measured, deterministic, reproducible
        # residual is 8.8e-4 mm^3 on a ~5347 mm^3 part (1.6e-7 relative) --
        # confirmed the same to 12 significant figures across repeated
        # recomputes, so this is boundary-precision noise, not drift. A real
        # placement bug (the thread reverting to the full uncut volume) is
        # many mm^3, not fractions of a thousandth -- delta=0.01 still
        # catches that with 10x margin over the observed noise floor.
        self.assertAlmostEqual(cut_obj.Shape.Volume, threaded, delta=0.01)

    def test_defaults_pick_M8_for_a_tap_drilled_hole(self):
        base = self._bored_block(bore_radius=3.4)
        circle = selection.resolve(base, self._bore_face(base, 3.4))
        d = api.defaults_for(circle)
        self.assertEqual(d["Mode"], form.INTERNAL)
        self.assertAlmostEqual(d["Diameter"], 8.0, places=3)
        self.assertAlmostEqual(d["Pitch"], 1.25, places=3)

    def test_bad_parameters_raise_rather_than_leaving_junk(self):
        base = self._bored_block()
        before = len(self.doc.Objects)
        with self.assertRaises(Exception):
            api.create_thread(self.doc, base, self._bore_face(base, 3.4),
                              {"CrestLand": 99.0})
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), before,
                         "failed creation left objects behind")

    def _face_z_range(self, obj, sub_name, axis):
        """The face's real axial extent, read from its own vertices -- not
        derived from `selection.resolve()`'s centre/length, since that is
        exactly what this test is checking a consumer of."""
        face = obj.Shape.getElement(sub_name)
        proj = [App.Vector(v.Point).dot(axis) for v in face.Vertexes]
        return min(proj), max(proj)

    def _threaded_at(self, cut_obj, z, radius=3.6, steps=24):
        """True if any azimuth at this z has had material removed.

        radius=3.6 sits inside the M8x1.25 cutter's active cutting envelope
        (between its "far" reach and its apex) but outside the virgin
        3.4mm bore wall, so a hit here can only be a thread groove, not the
        plain bore.  A helix crosses a given z at only a narrow phase band,
        so several azimuths must be sampled to find it (CLAUDE.md: keep the
        probe within one pitch's worth of resolution).
        """
        for deg in range(0, 360, 360 // steps):
            rad = math.radians(deg)
            p = App.Vector(radius * math.cos(rad), radius * math.sin(rad), z)
            if not cut_obj.Shape.isInside(p, 1e-7, True):
                return True
        return False

    def test_axial_coverage_reaches_both_ends_of_the_bore(self):
        """Regression: local_frame() anchors on the selected face's
        MIDPOINT (selection.py computes it that way deliberately -- Task 5),
        so feature.py must centre its sweep on that anchor. The original
        one-pitch offset instead started the sweep AT the midpoint and ran
        the full Length from there, so only the far half of a full-length
        bore ever got threaded, while the near half stayed a plain bore.
        """
        base = self._bored_block()
        face_name = self._bore_face(base, 3.4)
        circle = selection.resolve(base, face_name)
        z0, z1 = self._face_z_range(base, face_name, circle.axis)

        cut_obj = api.create_thread(self.doc, base, face_name)[1]

        margin = 1.5  # stay inside the true face ends, away from edge noise
        self.assertTrue(
            self._threaded_at(cut_obj, z0 + margin),
            "no thread material found near the near end (z=%.3f of [%.3f, "
            "%.3f])" % (z0 + margin, z0, z1))
        self.assertTrue(
            self._threaded_at(cut_obj, z1 - margin),
            "no thread material found near the far end (z=%.3f of [%.3f, "
            "%.3f])" % (z1 - margin, z0, z1))

    def test_reversed_stays_on_the_part(self):
        """Regression: a one-pitch (rather than half-height) offset keeps
        the sweep anchored at one point instead of centred on it, so
        reversing it walks the cutter off the part instead of merely
        flipping its sweep direction in place.
        """
        base_fwd = self._bored_block()
        face_fwd = self._bore_face(base_fwd, 3.4)
        circle = selection.resolve(base_fwd, face_fwd)
        z0, z1 = self._face_z_range(base_fwd, face_fwd, circle.axis)
        cutter_fwd = api.create_thread(self.doc, base_fwd, face_fwd)[0]
        forward_box = cutter_fwd.Shape.optimalBoundingBox()

        base_rev = self._bored_block()
        face_rev = self._bore_face(base_rev, 3.4)
        cutter_rev = api.create_thread(
            self.doc, base_rev, face_rev, {"Reversed": True})[0]
        reversed_box = cutter_rev.Shape.optimalBoundingBox()

        self.assertAlmostEqual(forward_box.ZMin, reversed_box.ZMin, places=3)
        self.assertAlmostEqual(forward_box.ZMax, reversed_box.ZMax, places=3)
        self.assertLessEqual(forward_box.ZMin, z0 + 1e-6,
                             "forward cutter does not reach the near end")
        self.assertGreaterEqual(forward_box.ZMax, z1 - 1e-6,
                                "forward cutter does not reach the far end")
        self.assertLessEqual(reversed_box.ZMin, z0 + 1e-6,
                             "reversed cutter walked off the near end")
        self.assertGreaterEqual(reversed_box.ZMax, z1 - 1e-6,
                                "reversed cutter walked off the far end")


if __name__ == "__main__":
    unittest.main()
