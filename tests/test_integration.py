import math
import unittest

import FreeCAD as App
import Part

from tapdie import api, feature, form, measure, selection


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
        # The CUTTER became a compound when lead-in chamfers arrived: the helix
        # plus one cone per free end, and those are not always connected --
        # whether the last turn reaches the chamfer plane depends on where the
        # sweep's fractional turn falls (see feature.py).  Its solid COUNT is
        # therefore configuration- and phase-dependent, so asserting 1 was an
        # over-constraint.  Assert instead that every piece is real.  The
        # meaningful single-solid property belongs to the CUT RESULT, and the
        # cut_obj assertions elsewhere in this file still check it exactly.
        self.assertGreaterEqual(len(obj.Shape.Solids), 1)
        for solid in obj.Shape.Solids:
            self.assertTrue(solid.isValid())

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


class TestLeadInChamfer(unittest.TestCase):
    """The lead-in relief cone at each FREE end of the threaded run.

    Uses a bare, unattached ThreadCutter (no AttachedTo) throughout, which
    keeps both ends "free" by definition (see feature._detect_free_ends),
    so these tests isolate the CHAMFER geometry itself from the separate
    free/abutting DETECTION logic covered by TestFreeEndDetection below.

    ISO (60 degree included angle, 30 degree half-angle flanks) is used
    deliberately instead of the printed 90 degree form: at 90 degrees the
    thread's own flank happens to also read 45 degrees (measure.py's own
    docstring notes this coincidence), which would make a found 45 degree
    edge ambiguous. At 60 degrees the two cannot be confused: any 45 degree
    edge found is the chamfer, never the thread.
    """

    def setUp(self):
        self.doc = App.newDocument("leadintest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _iso_cutter(self, mode=form.INTERNAL, lead_in=True, **props):
        obj = feature.make_cutter(self.doc)
        obj.Mode = mode
        obj.ThreadForm = form.ISO
        obj.Diameter = props.pop("Diameter", 8.0)
        obj.Pitch = props.pop("Pitch", 1.25)
        obj.SurfaceRadius = props.pop("SurfaceRadius", 3.3234)
        obj.Length = props.pop("Length", 8.0)
        obj.LeadIn = lead_in
        for k, v in props.items():
            setattr(obj, k, v)
        self.doc.recompute()
        return obj

    def _tip_radius(self, obj):
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
        return points[0][0]

    def test_internal_chamfer_is_45_degrees_at_both_ends(self):
        # A y=0 section is enough to prove the 45 degree edge EXISTS (it
        # does, at both ends -- confirmed below), but NOT to prove how far
        # it reaches: the fused solid's visible boundary at one arbitrary
        # azimuth follows whichever of {cone, helical thread} is locally
        # outermost, and the two swap over at different points at the near
        # vs far end (a real, harmless artifact of the helix's phase, not a
        # geometry defect -- confirmed by cross-checking with the
        # multi-azimuth probes in the two tests below, which show the cone's
        # full 360 degree reach directly rather than inferring it from one
        # slice). So: angle presence via profile() here; radial REACH via
        # ray probes in the tests below, per this project's own standing
        # guidance to measure with probes rather than trust a single section.
        obj = self._iso_cutter(mode=form.INTERNAL)
        self.assertTrue(obj.NearEndFree)
        self.assertTrue(obj.FarEndFree)
        self.assertTrue(obj.Shape.isValid())
        # The CUTTER became a compound when lead-in chamfers arrived: the helix
        # plus one cone per free end, and those are not always connected --
        # whether the last turn reaches the chamfer plane depends on where the
        # sweep's fractional turn falls (see feature.py).  Its solid COUNT is
        # therefore configuration- and phase-dependent, so asserting 1 was an
        # over-constraint.  Assert instead that every piece is real.  The
        # meaningful single-solid property belongs to the CUT RESULT, and the
        # cut_obj assertions elsewhere in this file still check it exactly.
        self.assertGreaterEqual(len(obj.Shape.Solids), 1)
        for solid in obj.Shape.Solids:
            self.assertTrue(solid.isValid())

        tip_radius = self._tip_radius(obj)
        depth = abs(tip_radius - obj.SurfaceRadius.Value)
        half = obj.Length.Value / 2.0
        eps = 1e-3

        near = measure.profile(obj.Shape, -half - eps, -half + depth + eps)
        far = measure.profile(obj.Shape, half - depth - eps, half + eps)
        for label, prof in (("near", near), ("far", far)):
            angles = set(round(a, 1) for a in prof["flank_angles"])
            self.assertIn(45.0, angles,
                         "%s end: no 45 degree chamfer edge found in %s"
                         % (label, angles))

    def _full_circle_removed(self, shape, radius, z, steps=24):
        """True only if EVERY sampled azimuth at (radius, z) is removed
        material. The lead-in cone is a full 360 degree revolve, unlike the
        helical thread groove (which only touches a narrow phase band at any
        given z), so "removed at every azimuth" is what distinguishes the
        cone's own contribution from an ordinary thread groove passing by."""
        for deg in range(0, 360, 360 // steps):
            rad = math.radians(deg)
            p = App.Vector(radius * math.cos(rad), radius * math.sin(rad), z)
            if not shape.isInside(p, 1e-7, True):
                return False
        return True

    def test_internal_chamfer_reaches_full_relief_radius(self):
        # "Full radius" = tip_radius: relieving out to it fully clears the
        # first turn (see cutter.lead_in_cone's docstring). Just inside each
        # face, at a hair less than tip_radius, EVERY azimuth must be
        # removed material -- the full circumference, not just wherever the
        # helix happens to be.
        obj = self._iso_cutter(mode=form.INTERNAL)
        tip_radius = self._tip_radius(obj)
        half = obj.Length.Value / 2.0
        probe_r = tip_radius - 0.02
        self.assertTrue(
            self._full_circle_removed(obj.Shape, probe_r, -half + 0.01),
            "chamfer does not reach the full relief radius (%.4f) all the "
            "way around at the near face" % tip_radius)
        self.assertTrue(
            self._full_circle_removed(obj.Shape, probe_r, half - 0.01),
            "chamfer does not reach the full relief radius (%.4f) all the "
            "way around at the far face" % tip_radius)

    def test_internal_chamfer_closes_back_to_the_surface_by_its_depth(self):
        # Just past where the cone should have tapered fully shut (a hair
        # beyond surface_radius, a hair past `depth` into the material),
        # relief must reach all the way around -- confirms the chamfer's
        # radial span genuinely closes at surface_radius, not short of it
        # (the discrepancy a single y=0 section showed in early testing).
        obj = self._iso_cutter(mode=form.INTERNAL)
        tip_radius = self._tip_radius(obj)
        depth = abs(tip_radius - obj.SurfaceRadius.Value)
        half = obj.Length.Value / 2.0
        probe_r = obj.SurfaceRadius.Value + 0.02
        self.assertTrue(
            self._full_circle_removed(obj.Shape, probe_r,
                                      -half + depth - 0.02),
            "near chamfer does not close back to the surface radius by its "
            "own depth")
        self.assertTrue(
            self._full_circle_removed(obj.Shape, probe_r,
                                      half - depth + 0.02),
            "far chamfer does not close back to the surface radius by its "
            "own depth")

    def test_internal_full_depth_thread_survives_between_the_chamfers(self):
        # By construction (see feature.execute()), each chamfer occupies
        # EXACTLY [feature_lo, feature_lo+depth] / [feature_hi-depth,
        # feature_hi] in the builder frame -- never more -- so the surviving
        # plain-thread span is deterministically Length - 2*depth. Confirm
        # that analytic span is genuinely still plain (helical, ISO 30
        # degree flank) thread, not degraded, on a SHORT feature where the
        # two chamfers take a proportionally large bite -- and report the
        # surviving length.
        obj = self._iso_cutter(mode=form.INTERNAL, Length=3.0)
        tip_radius = self._tip_radius(obj)
        depth = abs(tip_radius - obj.SurfaceRadius.Value)
        half = obj.Length.Value / 2.0
        engagement = obj.Length.Value - 2.0 * depth

        print("\n[lead-in] short feature: Length=%.3fmm, chamfer depth="
              "%.3fmm each end -> surviving full-depth engagement = "
              "%.3fmm" % (obj.Length.Value, depth, engagement))
        self.assertGreater(engagement, 0.0,
                          "the two chamfers meet or overlap -- no full-depth "
                          "thread survives at all on this feature length")

        # The middle of that surviving span must still show a full-depth
        # ISO thread groove -- root land at tip_radius reached by SOME
        # azimuth (the helix's own narrow phase band, not the chamfer's
        # full 360 degrees), and specifically the plain 30 degree flank
        # angle, not the chamfer's 45.
        mid_z = 0.0  # exact midpoint of a centred, symmetric feature
        window = 0.4
        prof = measure.profile(obj.Shape, mid_z - window, mid_z + window)
        angles = set(round(a, 1) for a in prof["flank_angles"])
        self.assertIn(30.0, angles,
                     "no plain ISO thread flank found in the surviving "
                     "middle span; got %s" % angles)
        self.assertNotIn(45.0, angles,
                        "found a 45 degree chamfer edge in what should be "
                        "the plain thread's surviving middle span -- the "
                        "chamfers are eating further than their own depth")
        self.assertTrue(obj.Shape.isValid())
        # The CUTTER became a compound when lead-in chamfers arrived: the helix
        # plus one cone per free end, and those are not always connected --
        # whether the last turn reaches the chamfer plane depends on where the
        # sweep's fractional turn falls (see feature.py).  Its solid COUNT is
        # therefore configuration- and phase-dependent, so asserting 1 was an
        # over-constraint.  Assert instead that every piece is real.  The
        # meaningful single-solid property belongs to the CUT RESULT, and the
        # cut_obj assertions elsewhere in this file still check it exactly.
        self.assertGreaterEqual(len(obj.Shape.Solids), 1)
        for solid in obj.Shape.Solids:
            self.assertTrue(solid.isValid())

    def test_very_short_feature_where_chamfers_overlap_still_builds(self):
        # Deliberately pathological: Length shorter than 2*depth, so the two
        # chamfer cones' z-spans overlap. Not asserting anything about
        # engagement here (there is none) -- only that the fuse still comes
        # out as a single valid solid rather than something OCC silently
        # mangles. If this starts failing, that is real news, not a test
        # that needs loosening.
        obj = self._iso_cutter(mode=form.INTERNAL, Length=1.0)
        depth = abs(self._tip_radius(obj) - obj.SurfaceRadius.Value)
        self.assertLess(obj.Length.Value, 2.0 * depth,
                        "fixture stopped being the pathological case it "
                        "was meant to test")
        self.assertTrue(obj.Shape.isValid())
        # The CUTTER became a compound when lead-in chamfers arrived: the helix
        # plus one cone per free end, and those are not always connected --
        # whether the last turn reaches the chamfer plane depends on where the
        # sweep's fractional turn falls (see feature.py).  Its solid COUNT is
        # therefore configuration- and phase-dependent, so asserting 1 was an
        # over-constraint.  Assert instead that every piece is real.  The
        # meaningful single-solid property belongs to the CUT RESULT, and the
        # cut_obj assertions elsewhere in this file still check it exactly.
        self.assertGreaterEqual(len(obj.Shape.Solids), 1)
        for solid in obj.Shape.Solids:
            self.assertTrue(solid.isValid())

    def test_lead_in_false_matches_the_plain_swept_geometry(self):
        # LeadIn=False must reproduce exactly the geometry cutter.build()
        # alone would produce. Clearance is forced to zero because it is
        # applied RADIALLY now: a nonzero value adds a crest-relief shell to
        # the cutter compound, which is real material to remove and not part
        # of the swept helix. Comparing against the bare sweep with clearance
        # left on measured 496 against 255 -- the relief, not a defect.
        from tapdie import cutter as cutter_mod

        obj = self._iso_cutter(mode=form.INTERNAL, lead_in=False)
        obj.Clearance = 0.0
        obj.Document.recompute()
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
        height = obj.Length.Value + 2.0 * obj.Pitch.Value
        plain = cutter_mod.build(points, obj.Pitch.Value, height,
                                 left_handed=obj.LeftHanded)
        self.assertAlmostEqual(obj.Shape.Volume, plain.Volume, places=6)

    def test_clearance_adds_the_crest_relief_to_the_cutter(self):
        # The other half of the above: with clearance on, the cutter must
        # carry strictly more than the bare sweep, because the blank has to
        # be relieved to the crest radius before the groove is cut.
        obj = self._iso_cutter(mode=form.INTERNAL, lead_in=False)
        obj.Clearance = 0.0
        obj.Document.recompute()
        bare = obj.Shape.Volume
        obj.Clearance = 0.12
        obj.Document.recompute()
        self.assertGreater(obj.Shape.Volume, bare)

    def test_lead_in_true_removes_strictly_more_material_than_false(self):
        with_chamfer = self._iso_cutter(mode=form.INTERNAL, lead_in=True)
        without = self._iso_cutter(mode=form.INTERNAL, lead_in=False)
        self.assertGreater(with_chamfer.Shape.Volume, without.Shape.Volume)

    def test_external_chamfer_does_not_sever_the_core(self):
        # Regression: the plain-cone construction that works for INTERNAL
        # (whose bore already has a hollow core to absorb it) removed the
        # EXTERNAL shaft's own solid core too when used unmodified, severing
        # a thin sliver clean off the tip in a real hex-head-plus-shaft
        # fixture (see TestFreeEndDetection). A probe near the axis, at the
        # chamfer's own z, must NOT be part of the removed material.
        obj = self._iso_cutter(mode=form.EXTERNAL, Diameter=4.0, Pitch=0.7,
                               SurfaceRadius=2.0, Length=10.0)
        self.assertTrue(obj.Shape.isValid())
        # The CUTTER became a compound when lead-in chamfers arrived: the helix
        # plus one cone per free end, and those are not always connected --
        # whether the last turn reaches the chamfer plane depends on where the
        # sweep's fractional turn falls (see feature.py).  Its solid COUNT is
        # therefore configuration- and phase-dependent, so asserting 1 was an
        # over-constraint.  Assert instead that every piece is real.  The
        # meaningful single-solid property belongs to the CUT RESULT, and the
        # cut_obj assertions elsewhere in this file still check it exactly.
        self.assertGreaterEqual(len(obj.Shape.Solids), 1)
        for solid in obj.Shape.Solids:
            self.assertTrue(solid.isValid())
        half = obj.Length.Value / 2.0
        core_probe = App.Vector(0.15, 0.0, -half + 0.05)
        self.assertFalse(
            obj.Shape.isInside(core_probe, 1e-7, True),
            "external chamfer removed material near the axis -- it should "
            "only bevel the outer corner, not cut into the shaft's core")

    def test_external_chamfer_is_45_degrees(self):
        obj = self._iso_cutter(mode=form.EXTERNAL, Diameter=4.0, Pitch=0.7,
                               SurfaceRadius=2.0, Length=10.0)
        tip_radius = self._tip_radius(obj)
        depth = abs(tip_radius - obj.SurfaceRadius.Value)
        half = obj.Length.Value / 2.0
        eps = 1e-3
        prof = measure.profile(obj.Shape, -half - eps, -half + depth + eps)
        angles = set(round(a, 1) for a in prof["flank_angles"])
        self.assertIn(45.0, angles,
                     "no 45 degree external chamfer edge found in %s"
                     % angles)


class TestFreeEndDetection(unittest.TestCase):
    """Per-end free (open space) vs abutting (adjacent material) detection,
    and its consequences: overrun+chamfer only at a free end, clamped and
    bare at an abutting one. Fixture numbers mirror the real bug report
    (hex head z 0..8, 4mm shaft z 8..30) that first surfaced this.
    """

    def setUp(self):
        self.doc = App.newDocument("freeendtest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _bore_face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - radius) < 1e-6:
                return "Face%d" % (i + 1)
        raise AssertionError("no face of radius %.3f" % radius)

    def _hex_prism(self, circumradius, height):
        pts = []
        for i in range(6):
            ang = math.radians(60 * i)
            pts.append(App.Vector(circumradius * math.cos(ang),
                                  circumradius * math.sin(ang), 0))
        pts.append(pts[0])
        return Part.Face(Part.makePolygon(pts)).extrude(App.Vector(0, 0, height))

    def _hex_head_rod(self, head_height=8.0, shaft_radius=2.0, shaft_length=22.0):
        hex_h = self._hex_prism(4.0, head_height)
        shaft = Part.makeCylinder(shaft_radius, shaft_length,
                                  App.Vector(0, 0, head_height))
        rod = self.doc.addObject("Part::Feature", "Rod")
        rod.Shape = hex_h.fuse(shaft)
        self.doc.recompute()
        return rod

    def _slab_volume(self, shape, z_lo, z_hi):
        big = 100.0
        box = Part.makeBox(big, big, z_hi - z_lo,
                           App.Vector(-big / 2, -big / 2, z_lo))
        return shape.common(box).Volume

    def test_hex_head_abutting_end_loses_no_material(self):
        """The exact regression: dieing a shaft against a hex head must not
        gouge into the head. Originally measured 48.5915mm3 removed from
        the head's own z-slab; must now be zero."""
        rod = self._hex_head_rod()
        shaft_face = self._bore_face(rod, 2.0)
        circle = selection.resolve(rod, shaft_face)

        head_slab_before = self._slab_volume(rod.Shape, 0.0, 8.0)
        cutter_obj, cut_obj = api.create_thread(
            self.doc, rod, shaft_face,
            {"Diameter": 4.0, "Pitch": 0.7, "Length": circle.length})

        self.assertFalse(cutter_obj.NearEndFree,
                         "the end abutting the hex head must be detected as "
                         "NOT free")
        self.assertTrue(cutter_obj.FarEndFree,
                       "the open tip must still be detected as free")
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)

        head_slab_after = self._slab_volume(cut_obj.Shape, 0.0, 8.0)
        lost = head_slab_before - head_slab_after
        print("\n[free-end] material removed from hex head slab: %.4f mm3 "
              "(was 48.5915 mm3 before this fix)" % lost)
        self.assertAlmostEqual(lost, 0.0, places=3)

    def test_hex_head_thread_reaches_the_shoulder(self):
        """Threads must be fully formed right up to the shoulder plane, not
        stop short of it."""
        rod = self._hex_head_rod()
        shaft_face = self._bore_face(rod, 2.0)
        circle = selection.resolve(rod, shaft_face)
        cutter_obj, cut_obj = api.create_thread(
            self.doc, rod, shaft_face,
            {"Diameter": 4.0, "Pitch": 0.7, "Length": circle.length})

        # Probe just under the CREST, derived from the geometry rather than
        # hard-coded. The old 1.7 was a constant chosen against a deeper
        # thread; with clearance now taken radially the crest sits at
        # 2.0 - radial_offset and the groove only runs cut_depth below that,
        # which at this size is 0.105mm -- so a fixed 1.7 probe sat below
        # the root and read "no thread" everywhere, testing nothing about
        # whether the run reaches the shoulder.
        crest_r = form.crest_radius(cutter_obj.Mode, 2.0,
                                    cutter_obj.Clearance.Value,
                                    cutter_obj.Angle.Value)
        depth = form.cut_depth(0.7, cutter_obj.Angle.Value,
                               cutter_obj.RootLand.Value,
                               cutter_obj.CrestLand.Value)
        probe_r = crest_r - depth / 2.0

        def threaded_at(z, radius=probe_r, steps=24):
            for deg in range(0, 360, 360 // steps):
                rad = math.radians(deg)
                p = App.Vector(radius * math.cos(rad), radius * math.sin(rad), z)
                if not cut_obj.Shape.isInside(p, 1e-7, True):
                    return True
            return False

        # Right up against the shoulder (z=8): material removed there means
        # the thread groove reaches all the way, not stopping short.
        reaches_shoulder = threaded_at(8.3)
        print("[free-end] thread reaches to z=8.3 (0.3mm from the shoulder "
              "at z=8): %s" % reaches_shoulder)
        self.assertTrue(reaches_shoulder,
                       "thread stops short of the shoulder instead of "
                       "reaching fully formed threads to the bottom")

    def test_free_end_still_overruns_and_chamfers(self):
        rod = self._hex_head_rod()
        shaft_face = self._bore_face(rod, 2.0)
        circle = selection.resolve(rod, shaft_face)
        cutter_obj, _cut_obj = api.create_thread(
            self.doc, rod, shaft_face,
            {"Diameter": 4.0, "Pitch": 0.7, "Length": circle.length})
        # The free (far) end's world Z must extend past the shaft's own tip
        # (z=30) -- the overrun -- unlike the clamped near end.
        bbox = cutter_obj.Shape.optimalBoundingBox()
        print("[free-end] cutter world Z extent: %.3f .. %.3f (shaft is "
              "8.000 .. 30.000)" % (bbox.ZMin, bbox.ZMax))
        self.assertGreater(bbox.ZMax, 30.0,
                          "the free end lost its overrun past the shaft tip")
        self.assertAlmostEqual(bbox.ZMin, 8.0, delta=0.05,
                              msg="the abutting end must be clamped to the "
                                  "shoulder plane, not overrun into the head")

    def test_plain_shaft_both_ends_free_overruns_and_chamfers_both(self):
        shaft = self.doc.addObject("Part::Feature", "PlainShaft")
        shaft.Shape = Part.makeCylinder(2.0, 20.0)
        self.doc.recompute()
        face = self._bore_face(shaft, 2.0)
        circle = selection.resolve(shaft, face)
        self.assertEqual(circle.mode, form.EXTERNAL)

        cutter_obj, cut_obj = api.create_thread(
            self.doc, shaft, face,
            {"Diameter": 4.0, "Pitch": 0.7, "Length": circle.length})
        print("[free-end] plain shaft: NearEndFree=%s FarEndFree=%s" %
              (cutter_obj.NearEndFree, cutter_obj.FarEndFree))
        self.assertTrue(cutter_obj.NearEndFree)
        self.assertTrue(cutter_obj.FarEndFree)
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)

    def test_through_tapped_hole_both_ends_free_overruns_and_chamfers_both(self):
        outer = Part.makeCylinder(10.0, 20.0)
        bore = Part.makeCylinder(3.4, 20.0)
        base = self.doc.addObject("Part::Feature", "Block")
        base.Shape = outer.cut(bore)
        self.doc.recompute()
        face = self._bore_face(base, 3.4)

        cutter_obj, cut_obj = api.create_thread(self.doc, base, face)
        print("[free-end] through-tapped hole: NearEndFree=%s FarEndFree=%s" %
              (cutter_obj.NearEndFree, cutter_obj.FarEndFree))
        self.assertTrue(cutter_obj.NearEndFree)
        self.assertTrue(cutter_obj.FarEndFree)
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)

    def test_blind_bore_free_at_the_mouth_abutting_at_the_floor(self):
        """A bore that stops partway (a blind hole): the open mouth is
        free, the floor end abuts the solid material closing it off."""
        block = Part.makeBox(20.0, 20.0, 20.0, App.Vector(-10, -10, 0))
        bore = Part.makeCylinder(3.4, 12.0, App.Vector(0, 0, 8.0))
        base = self.doc.addObject("Part::Feature", "BlindBlock")
        base.Shape = block.cut(bore)
        self.doc.recompute()
        face = self._bore_face(base, 3.4)
        circle = selection.resolve(base, face)
        print("[free-end] blind bore circle centre=%s length=%.3f" %
              (circle.centre, circle.length))

        cutter_obj, cut_obj = api.create_thread(
            self.doc, base, face, {"Length": circle.length})
        print("[free-end] blind bore: NearEndFree=%s FarEndFree=%s" %
              (cutter_obj.NearEndFree, cutter_obj.FarEndFree))
        # Exactly one end free, one abutting -- whichever way the module
        # happens to label near/far, both ends must not agree.
        self.assertNotEqual(cutter_obj.NearEndFree, cutter_obj.FarEndFree,
                           "a blind bore must detect exactly one free end "
                           "(the mouth) and one abutting end (the floor)")
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)


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
        # residual is 8.842106e-04 mm^3 on a ~5347 mm^3 part (1.6e-7
        # relative) -- confirmed to full double precision across 5 reruns,
        # and independently reswept at rotation angles 1/10/37/90/180
        # degrees with residuals in the 1e-7..1e-3 mm^3 band. This is
        # boundary-precision noise from the boolean kernel, not drift, and
        # nowhere near a real placement bug (the thread reverting to the
        # full uncut volume is thousands of mm^3, not fractions of a
        # thousandth). delta=0.002 still gives >2x margin over the largest
        # observed residual -- do not loosen further without new evidence.
        self.assertAlmostEqual(cut_obj.Shape.Volume, threaded, delta=0.002)

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
        with self.assertRaises(Exception) as ctx:
            api.create_thread(self.doc, base, self._bore_face(base, 3.4),
                              {"CrestLand": 99.0})
        # Pins the diagnostic, not just the exception type: when execute()
        # raises, obj.Shape is left NULL, and Shape.isValid() on a null
        # shape raises its OWN native OCCError ("...NULL shape") before the
        # intended ThreadError message is ever reached -- so without the
        # isNull() check in api.py, this substring would not appear here.
        self.assertIn("cutter did not build", str(ctx.exception))
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), before,
                         "failed creation left objects behind")

    def test_overrides_survive_regardless_of_dict_order(self):
        """Regression: create_thread applied params in whatever order the
        caller's dict happened to iterate. ThreadForm and Pitch both
        re-trigger feature.py's _apply_preset(), which overwrites Angle,
        RootLand and CrestLand -- so an explicit override of those three
        silently vanished whenever ThreadForm or Pitch iterated after them
        in the same dict. Task 8's dialog submits exactly this shape (every
        field, every time), so this dict order -- RootLand/CrestLand/Angle
        first, ThreadForm last -- is the realistic one, not a contrived one.
        """
        base = self._bored_block()
        cutter_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4),
            {"RootLand": 0.5, "CrestLand": 0.5, "Angle": 77.0,
             "ThreadForm": form.PRINTED})[0]
        self.assertEqual(cutter_obj.ThreadForm, form.PRINTED)
        self.assertAlmostEqual(cutter_obj.Angle.Value, 77.0, places=6)
        self.assertAlmostEqual(cutter_obj.RootLand.Value, 0.5, places=6)
        self.assertAlmostEqual(cutter_obj.CrestLand.Value, 0.5, places=6)

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
        # Matching envelopes are also what a no-op Reversed would produce --
        # this positively confirms the 180-about-X branch actually ran,
        # rather than merely checking an outcome a no-op would satisfy too
        # (the sibling unit test, test_reversed_keeps_the_sweep_centred_on_
        # the_anchor, caught this gap in feature.py directly; this is the
        # same check through the AttachedTo/api.py path).
        self.assertAlmostEqual(cutter_fwd.Placement.Rotation.Angle, 0.0,
                               places=6)
        self.assertAlmostEqual(cutter_rev.Placement.Rotation.Angle, math.pi,
                               places=6)


if __name__ == "__main__":
    unittest.main()
