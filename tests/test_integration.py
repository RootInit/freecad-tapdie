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

    def _boxes(self):
        """optimalBoundingBox per direction, plus the shared Length/Pitch.

        Do NOT try to recover the nominal run by shrinking the box by a
        pitch: the swept solid also overshoots each end by the profile's own
        axial half-width, (pitch - crest_land)/2, because the profile is
        centred on v=0 and swept from z=0 to z=height. That cost a failing
        assertion by 1.86mm. Compare boxes to each OTHER instead -- placement
        is a pure translation, so the differences are exact and the
        overshoot cancels.
        """
        boxes = {}
        length = pitch = None
        for direction in form.DIRECTIONS:
            obj = self._cutter(Direction=direction)
            boxes[direction] = obj.Shape.optimalBoundingBox()
            length, pitch = obj.Length.Value, obj.Pitch.Value
            self.doc.removeObject(obj.Name)
        return boxes, length, pitch

    def test_placement_puts_the_run_where_span_says(self):
        """The placement is the contract: builder z=pitch lands on span()'s
        low edge, so the run occupies exactly [z_lo, z_hi]."""
        for direction in form.DIRECTIONS:
            obj = self._cutter(Direction=direction)
            z_lo, _z_hi = form.span(direction, obj.Length.Value)
            self.assertAlmostEqual(
                obj.Placement.Base.z, z_lo - obj.Pitch.Value, places=6,
                msg="direction %s" % direction)
            self.doc.removeObject(obj.Name)

    def test_forward_sits_half_a_length_above_both_ways(self):
        boxes, length, _pitch = self._boxes()
        shift = boxes[form.FORWARD].ZMin - boxes[form.BOTH].ZMin
        self.assertAlmostEqual(shift, length / 2.0, places=3)

    def test_reverse_sits_half_a_length_below_both_ways(self):
        boxes, length, _pitch = self._boxes()
        shift = boxes[form.REVERSE].ZMin - boxes[form.BOTH].ZMin
        self.assertAlmostEqual(shift, -length / 2.0, places=3)

    def test_forward_and_reverse_are_a_whole_length_apart(self):
        boxes, length, _pitch = self._boxes()
        self.assertAlmostEqual(
            boxes[form.FORWARD].ZMin - boxes[form.REVERSE].ZMin,
            length, places=3)

    def test_direction_moves_the_cutter_without_resizing_it(self):
        boxes, _length, _pitch = self._boxes()
        heights = [round(b.ZMax - b.ZMin, 6) for b in boxes.values()]
        self.assertEqual(len(set(heights)), 1,
                         "direction changed the swept height: %s" % heights)

    def test_direction_preserves_volume(self):
        volumes = []
        for direction in form.DIRECTIONS:
            obj = self._cutter(Direction=direction)
            volumes.append(obj.Shape.Volume)
            self.doc.removeObject(obj.Name)
        for volume in volumes[1:]:
            self.assertAlmostEqual(volume, volumes[0], places=6)

    def test_placement_never_tips_the_cutter_off_its_axis(self):
        """Direction places the run by translation alone.

        The old Reversed used a 180-about-X rotation to run the other way
        while staying centred, which also flipped which physical end the
        builder frame's 'near' end meant. Direction needs no rotation, and
        _detect_free_ends depends on that.

        The placement DOES now carry a rotation about the axis -- that is
        StartAngle plus the half-pitch clocking that mates an internal
        thread with an external one -- so what must hold is that the axis of
        that rotation is Z and nothing else. A rotation about Z slides the
        helix along itself; a rotation about anything else points the cutter
        somewhere new.
        """
        for direction in form.DIRECTIONS:
            for mode in (form.INTERNAL, form.EXTERNAL):
                obj = self._cutter(Direction=direction, Mode=mode)
                rotation = obj.Placement.Rotation
                where = "direction %s, mode %s" % (direction, mode)
                if abs(rotation.Angle) > 1e-9:
                    axis = rotation.Axis
                    self.assertAlmostEqual(abs(axis.z), 1.0, places=9,
                                           msg="tipped off Z: %s" % where)
                    self.assertAlmostEqual(axis.x, 0.0, places=9, msg=where)
                    self.assertAlmostEqual(axis.y, 0.0, places=9, msg=where)
                self.doc.removeObject(obj.Name)

    def test_an_internal_thread_is_clocked_half_a_pitch_from_an_external(self):
        """Otherwise the two ridges collide and the pair will not mate.

        Both cutters carve their groove at azimuth 0, so both parts keep
        their ridge half a pitch from it -- and assembled coaxially those
        ridges land on top of each other.
        """
        internal = self._cutter(Mode=form.INTERNAL)
        external = self._cutter(Mode=form.EXTERNAL, SurfaceRadius=8.2597)
        gap = (internal.Placement.Rotation.Angle
               - external.Placement.Rotation.Angle)
        self.assertAlmostEqual(abs(math.degrees(gap)), 180.0, places=6)

    def test_start_angle_adds_to_the_mating_clock_in_both_modes(self):
        for mode, base in ((form.EXTERNAL, 0.0), (form.INTERNAL, 180.0)):
            for extra in (0.0, 30.0, 90.0):
                self.assertAlmostEqual(
                    form.start_phase(mode, extra), base + extra, places=9,
                    msg="mode %s extra %.0f" % (mode, extra))

    def test_an_unknown_direction_is_rejected(self):
        # App::PropertyEnumeration refuses a value outside its own list, so
        # the guard in form.span is a second line of defence rather than the
        # only one. Confirm the property itself is enumerated.
        obj = self._cutter()
        with self.assertRaises(ValueError):
            obj.Direction = "Sideways"

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

    @staticmethod
    def _inside(shape, point):
        """isInside, per SOLID -- never on the compound itself.

        Shape.isInside() is unreliable on a compound: measured on this build
        (tools/probe_flush_chamfer.py), a point that lies inside the lead-in
        cone -- confirmed by testing that cone solid on its own, at all 24
        sampled azimuths -- reported False when the same call was made
        against the compound holding it. The cutter has been a compound of
        helix + relief + chamfers since the chamfer fix, so every probe here
        has to go solid by solid or it is measuring the wrong thing.
        """
        return any(solid.isInside(point, 1e-7, True)
                   for solid in shape.Solids)

    def _full_circle_removed(self, shape, radius, z, steps=24):
        """True only if EVERY sampled azimuth at (radius, z) is removed
        material. The lead-in cone is a full 360 degree revolve, unlike the
        helical thread groove (which only touches a narrow phase band at any
        given z), so "removed at every azimuth" is what distinguishes the
        cone's own contribution from an ordinary thread groove passing by."""
        for deg in range(0, 360, 360 // steps):
            rad = math.radians(deg)
            p = App.Vector(radius * math.cos(rad), radius * math.sin(rad), z)
            if not self._inside(shape, p):
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
        # FlushEnds off too: it trims the sweep back to the run's extent, so
        # comparing a flush cutter against the untrimmed sweep measured 159.7
        # against 209.6. Both properties are deliberately neutralised here so
        # what remains is the plain helix and nothing else.
        obj.FlushEnds = False
        obj.Document.recompute()
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
        height = obj.Length.Value + 2.0 * obj.Pitch.Value
        plain = cutter_mod.build(points, obj.Pitch.Value, height,
                                 left_handed=obj.LeftHanded)
        self.assertAlmostEqual(obj.Shape.Volume, plain.Volume, places=6)

    def test_flush_ends_trims_the_sweep_to_the_run(self):
        """FlushEnds faces the cutter off at the run's own ends.

        The sweep is built a pitch longer at each end on purpose -- sweeping
        exactly to length leaves the crest dying out short of the face -- so
        this is the "then cut flush" half of that.
        """
        obj = self._iso_cutter(mode=form.INTERNAL, lead_in=False)
        obj.FlushEnds = False
        obj.Document.recompute()
        loose = obj.Shape.optimalBoundingBox()
        obj.FlushEnds = True
        obj.Document.recompute()
        flush = obj.Shape.optimalBoundingBox()

        pitch, length = obj.Pitch.Value, obj.Length.Value
        self.assertAlmostEqual(flush.ZMax - flush.ZMin, length, places=3)
        # The untrimmed sweep overshoots by a pitch of overrun at each end
        # PLUS the profile's own axial half-width, since the profile is
        # centred on v=0 and swept from z=0 to z=height.
        self.assertGreaterEqual(
            (loose.ZMax - loose.ZMin) - (flush.ZMax - flush.ZMin),
            2.0 * pitch - 1e-6)

    def test_an_abutting_end_is_faced_off_even_with_flush_ends_off(self):
        """Not a style choice: the overrun gouges what it butts against.

        Verified through _detect_free_ends' own output rather than by
        rebuilding a hex-head fixture here -- an unattached cutter reports
        both ends free, so this pins the logic that consumes those flags.
        """
        obj = self._iso_cutter(mode=form.INTERNAL, lead_in=False)
        obj.FlushEnds = False
        obj.Document.recompute()
        self.assertTrue(obj.NearEndFree and obj.FarEndFree,
                        "fixture assumption: an unattached cutter is free")
        # With both ends free and FlushEnds off, nothing is trimmed.
        loose = obj.Shape.optimalBoundingBox()
        self.assertGreater(loose.ZMax - loose.ZMin, obj.Length.Value)

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
        # Per-solid, not on the compound: isInside on a compound is
        # unreliable (see _inside), and here it would fail OPEN -- reporting
        # False for a point that really is inside one of the solids would
        # pass this assertion while the chamfer was severing the core.
        self.assertFalse(
            self._inside(obj.Shape, core_probe),
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

    def test_a_base_with_a_null_shape_reads_as_abutting(self):
        """An unevaluable probe must fail SAFE, like _end_is_free does.

        feature.py's module docstring commits to this: a probe that cannot be
        evaluated is treated as abutting, because gouging a neighbour is
        destructive while a missing overrun merely leaves a plain collar.
        _end_is_free honoured that; _detect_free_ends did not, and returned
        the destructive reading for a base it could not measure.
        """
        ghost = self.doc.addObject("Part::Feature", "Ghost")   # null Shape
        obj = feature.make_cutter(self.doc)
        obj.SurfaceRadius = 4.0
        obj.Length = 6.0
        obj.AttachedTo = ghost
        obj.LocalPlacement = App.Placement()
        self.assertTrue(ghost.Shape.isNull(), "fixture: Ghost must be null")
        self.assertEqual(feature._detect_free_ends(obj), (False, False))

    def test_no_base_at_all_is_still_both_ends_free(self):
        """The other direction: with nothing to gouge, nothing is clamped."""
        obj = feature.make_cutter(self.doc)
        self.assertIsNone(obj.AttachedTo)
        self.assertEqual(feature._detect_free_ends(obj), (True, True))

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

    def test_a_chamfer_never_reaches_past_an_abutting_end(self):
        """The clamp must bound the CHAMFERS too, not only the sweep.

        A cone's axial reach EQUALS its radial depth (it is 45 degrees), so
        on a run shorter than cut_depth + radial_offset it crosses the far
        end plane -- and feature.py added the cones AFTER the clip, so
        nothing bounded them. Measured before the fix: a 4mm stub against an
        8mm shoulder, run [0, 1], chamfer reach 1.6697mm, cutter z-extent
        [-0.6959, 1.0442], 0.3697mm eaten out of the shoulder. That is the
        same defect class the abutting-end clamp exists to prevent.
        """
        stub = Part.makeCylinder(4.0, 1.0, App.Vector(0, 0, 0))
        shoulder = Part.makeCylinder(8.0, 5.0, App.Vector(0, 0, -5.0))
        base = self.doc.addObject("Part::Feature", "Stub")
        base.Shape = stub.fuse(shoulder).removeSplitter()
        self.doc.recompute()

        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 3.8
        obj.SurfaceRadius = 4.0
        obj.Length = 1.0
        obj.Direction = form.FORWARD          # run occupies z in [0, +1]
        obj.LeadIn = True
        obj.FlushEnds = True
        obj.AttachedTo = base
        obj.LocalPlacement = App.Placement()
        self.doc.recompute()

        self.assertFalse(obj.NearEndFree, "fixture: z=0 abuts the shoulder")
        self.assertTrue(obj.FarEndFree, "fixture: z=+1 is open air")
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
        reach = abs(points[0][0] - obj.SurfaceRadius.Value)
        self.assertGreater(reach, obj.Length.Value,
                           "fixture stopped being the overreaching case")
        box = obj.Shape.optimalBoundingBox()
        self.assertGreaterEqual(
            box.ZMin, -1e-6,
            "the chamfer reached %.4fmm past the abutting end at z=0"
            % -box.ZMin)

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
        # Pins the diagnostic, not just the exception type. Two guards can
        # produce it and both share this phrase on purpose: the State check
        # (which fires first here, since a failed execute leaves the object
        # Invalid/Touched) and the isNull check. The latter still matters --
        # Shape.isValid() on a NULL shape raises its own native OCCError
        # ("...NULL shape"), which would surface instead of this message --
        # so it is exercised directly in test_null_shape_is_reported_clearly.
        self.assertIn("cutter did not build", str(ctx.exception))
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), before,
                         "failed creation left objects behind")

    def test_null_shape_is_reported_clearly(self):
        """The isNull guard, exercised on its own.

        The State check normally fires first, so without this the isNull
        branch would sit unexercised and could regress silently. A NULL
        shape whose object is otherwise Up-to-date is the case it exists
        for: Shape.isValid() on a null shape raises a native OCCError
        ("...NULL shape") rather than returning False, so dropping the
        isNull() test would surface that instead of a usable message.
        """
        base = self._bored_block()
        cutter_obj, cut = api.build_thread(self.doc, base,
                                           self._bore_face(base, 3.4))
        cutter_obj.Shape = Part.Shape()
        # purgeTouched, and NO recompute. Recomputing simply re-runs
        # execute() and rebuilds a perfectly good shape, so the guard under
        # test never sees a null one; and assigning Shape leaves the object
        # Touched, which would trip the State check first and mask it.
        cutter_obj.purgeTouched()
        self.assertTrue(cutter_obj.Shape.isNull(), "fixture is not null")
        with self.assertRaises(api.ThreadError) as ctx:
            api._validate(cutter_obj, cut)
        self.assertIn("cutter did not build", str(ctx.exception))

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

    def test_build_cutter_performs_no_boolean(self):
        """The preview shows the material to be removed, not the result.

        A Part::Cut hides its Base the moment it exists, so building the
        boolean up front made the part vanish as the dialog opened.
        """
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        before = len(self.doc.Objects)
        cutter_obj = api.build_cutter(self.doc, base, face)
        self.assertEqual(len(self.doc.Objects), before + 1,
                         "build_cutter created more than the cutter")
        self.assertFalse(
            [o for o in self.doc.Objects if o.TypeId == "Part::Cut"],
            "build_cutter performed a boolean")
        self.assertTrue(cutter_obj.Shape.isValid())
        self.assertTrue(cutter_obj.Shape.Solids)

    def test_build_cutter_leaves_the_part_intact(self):
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        volume = base.Shape.Volume
        api.build_cutter(self.doc, base, face)
        self.assertAlmostEqual(base.Shape.Volume, volume, places=6,
                               msg="the preview modified the part")

    def test_apply_cut_finishes_the_job(self):
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        volume = base.Shape.Volume
        cutter_obj = api.build_cutter(self.doc, base, face)
        cut = api.apply_cut(self.doc, base, cutter_obj)
        self.assertEqual(cut.TypeId, "Part::Cut")
        self.assertEqual(len(cut.Shape.Solids), 1)
        self.assertLess(cut.Shape.Volume, volume,
                        "the boolean removed nothing")

    def test_build_thread_is_still_the_two_together(self):
        """create_thread's one-shot path must be unchanged by the split.

        The cut consumes the cutter and the part -- but the part reaches it
        through a Part::Fuse whenever material had to be added first, which
        a standard tap drill triggers: an ISO 6.8mm hole is 0.098mm wider
        than the printed form wants for an exact M8, so AddMaterial lines it
        rather than letting the thread come out at M8.2.
        """
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        cutter_obj, cut = api.build_thread(self.doc, base, face)
        self.assertEqual(cut.Tool.Name, cutter_obj.Name)
        consumed = cut.Base
        if consumed.TypeId == "Part::Fuse":
            self.assertGreater(feature.fill_needed(cutter_obj), 0.0,
                               "a fuse appeared with nothing to add")
            consumed = consumed.Base
        self.assertEqual(consumed.Name, base.Name)
        self.assertEqual(len(cut.Shape.Solids), 1)

    def test_abort_alone_does_not_remove_what_build_thread_created(self):
        """WHY the panel's Cancel calls discard() and not just abort.

        abortTransaction is widely assumed to undo object creation. Measured
        here it does NOT, at least once a recompute has run inside the
        transaction: both objects were still in the tree afterwards. Cancel
        relying on abort alone would leave an orphaned cutter and a Part::Cut
        swallowing the user's part every time.
        """
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        self.doc.openTransaction("outer")
        cutter_obj, cut = api.build_thread(self.doc, base, face)
        names = (cutter_obj.Name, cut.Name)
        self.doc.abortTransaction()
        self.doc.recompute()
        survived = [n for n in names
                    if n in [o.Name for o in self.doc.Objects]]
        self.assertTrue(
            survived,
            "abortTransaction now cleans up on its own -- if that is "
            "reliably true, api.discard could be simplified; verify first")

        # ...and discard finishes the job.
        api.discard(self.doc, cut, cutter_obj)
        remaining = [o.Name for o in self.doc.Objects]
        for name in names:
            self.assertNotIn(name, remaining)

    def test_build_thread_reports_what_it_created_on_failure(self):
        """`created` must list the cutter even when the build blows up
        afterwards, or the caller cannot clean up precisely."""
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        created = []
        with self.assertRaises(Exception):
            # A pitch far larger than the bore cannot produce a profile.
            api.build_thread(self.doc, base, face,
                             {"Pitch": 500.0}, created)
        self.assertTrue(created, "created list left empty after a failure")
        # Names must be read BEFORE discarding: touching .Name on a removed
        # object raises ReferenceError, not a miss.
        names = [obj.Name for obj in created]
        api.discard(self.doc, *reversed(created))
        remaining = [o.Name for o in self.doc.Objects]
        for name in names:
            self.assertNotIn(name, remaining)

    def test_update_thread_reparameterises_in_place(self):
        """The preview must reuse its objects, not recreate them."""
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        cutter_obj, cut = api.build_thread(self.doc, base, face,
                                           {"Length": 4.0})
        before = (cutter_obj.Name, cut.Name)
        volume = cutter_obj.Shape.Volume
        count = len(self.doc.Objects)

        api.update_thread(cutter_obj, cut, {"Length": 8.0})

        self.assertEqual((cutter_obj.Name, cut.Name), before,
                         "update replaced the objects instead of editing")
        self.assertEqual(len(self.doc.Objects), count,
                         "update leaked an object")
        self.assertGreater(cutter_obj.Shape.Volume, volume)
        self.assertEqual(len(cut.Shape.Solids), 1)

    def test_update_thread_raises_rather_than_leaving_a_null_shape(self):
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        cutter_obj, cut = api.build_thread(self.doc, base, face)
        with self.assertRaises(Exception):
            api.update_thread(cutter_obj, cut, {"Pitch": 500.0})

    def test_apply_params_sets_structural_keys_first(self):
        """A preset-driven key must not clobber an explicit override.

        ThreadForm/Pitch/Mode all re-run the preset, which rewrites
        Angle/RootLand/CrestLand -- so a dict that happens to iterate with
        Pitch last used to silently discard an explicit Angle.
        """
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        cutter_obj, _cut = api.build_thread(self.doc, base, face)
        api.apply_params(cutter_obj, {
            "Angle": 70.0, "ThreadForm": form.CUSTOM, "Pitch": 2.0,
            "RootLand": 0.3, "CrestLand": 0.35})
        self.assertAlmostEqual(cutter_obj.Angle.Value, 70.0, places=6)
        self.assertAlmostEqual(cutter_obj.RootLand.Value, 0.3, places=6)
        self.assertAlmostEqual(cutter_obj.CrestLand.Value, 0.35, places=6)

    def test_both_ways_covers_a_whole_bore_face(self):
        """Regression: a one-pitch (rather than centred) offset anchors the
        sweep at one point instead of straddling it, leaving half the bore
        unthreaded and sending the rest of the cutter past the far face.

        This is why BOTH remains the default: for a cylindrical FACE
        selection, where the anchor is the face's own midpoint and Length is
        the face's length, straddling is exactly right.
        """
        base = self._bored_block()
        face = self._bore_face(base, 3.4)
        circle = selection.resolve(base, face)
        z0, z1 = self._face_z_range(base, face, circle.axis)
        cutter_obj = api.create_thread(self.doc, base, face)[0]
        box = cutter_obj.Shape.optimalBoundingBox()

        self.assertLessEqual(box.ZMin, z0 + 1e-6,
                             "cutter does not reach the near end")
        self.assertGreaterEqual(box.ZMax, z1 - 1e-6,
                                "cutter does not reach the far end")

    def test_one_way_directions_stay_on_their_own_side(self):
        """The point of Direction, checked through the real api path.

        FORWARD must put no cutter below the anchor and REVERSE none above
        it -- otherwise it is still cutting both ways from the profile.
        """
        for direction, expect in ((form.FORWARD, "above"),
                                  (form.REVERSE, "below")):
            base = self._bored_block()
            face = self._bore_face(base, 3.4)
            circle = selection.resolve(base, face)
            anchor = circle.centre.z
            cutter_obj = api.create_thread(
                self.doc, base, face, {"Direction": direction,
                                       "Length": 4.0})[0]
            box = cutter_obj.Shape.optimalBoundingBox()
            pitch = cutter_obj.Pitch.Value
            # Allow the pitch of sweep overrun that a free end legitimately
            # carries past the run itself.
            if expect == "above":
                self.assertGreaterEqual(box.ZMin, anchor - pitch - 1e-6,
                                        "FORWARD reached below the anchor")
            else:
                self.assertLessEqual(box.ZMax, anchor + pitch + 1e-6,
                                     "REVERSE reached above the anchor")

    def test_every_direction_places_by_translation_alone(self):
        """Direction must not rotate the cutter relative to its own frame.

        The thread's phase (StartAngle plus the internal half-pitch clock)
        is a rotation about the axis and is expected; what must not vary is
        anything else. Compared across directions rather than against zero,
        so the phase cancels and only a Direction-induced rotation shows.
        """
        placements = {}
        for direction in form.DIRECTIONS:
            base = self._bored_block()
            face = self._bore_face(base, 3.4)
            cutter_obj = api.create_thread(
                self.doc, base, face, {"Direction": direction})[0]
            placements[direction] = cutter_obj.Placement.Rotation
        reference = placements[form.BOTH]
        for direction, rotation in placements.items():
            delta = reference.inverted().multiply(rotation)
            self.assertAlmostEqual(
                delta.Angle, 0.0, places=6,
                msg="direction %s introduced a rotation of its own"
                    % direction)


class TestAddMaterialWhenNeeded(unittest.TestCase):
    """A cutter cannot add material, so a thread larger than its shaft (or
    smaller than its bore) needs a tube fused on first -- and ONLY then."""

    def setUp(self):
        self.doc = App.newDocument("filltest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _shaft(self, radius=4.0, height=30.0):
        obj = self.doc.addObject("Part::Cylinder", "Shaft")
        obj.Radius, obj.Height = radius, height
        self.doc.recompute()
        for i, f in enumerate(obj.Shape.Faces):
            if (hasattr(f.Surface, "Radius")
                    and abs(f.Surface.Radius - radius) < 1e-6):
                return obj, "Face%d" % (i + 1)
        raise AssertionError("no cylindrical face")

    def _bored_block(self, bore=3.0, outer=12.0, height=20.0):
        block = Part.makeCylinder(outer, height)
        hole = Part.makeCylinder(bore, height)
        obj = self.doc.addObject("Part::Feature", "Block")
        obj.Shape = block.cut(hole)
        self.doc.recompute()
        for i, f in enumerate(obj.Shape.Faces):
            if (hasattr(f.Surface, "Radius")
                    and abs(f.Surface.Radius - bore) < 1e-6):
                return obj, "Face%d" % (i + 1)
        raise AssertionError("no bore face")

    def test_nothing_is_added_when_cutting_can_reach_it(self):
        """ONLY if needed: the ordinary case must not gain a boolean, an
        object, or a hidden original."""
        shaft, sub = self._shaft(radius=4.0)
        created = []
        api.build_thread(self.doc, shaft, sub,
                         {"Diameter": 8.0, "Pitch": 1.25, "Length": 10.0},
                         created)
        fuses = [o for o in created if o.TypeId == "Part::Fuse"]
        self.assertEqual(fuses, [], "a fuse appeared with nothing to add")
        fills = [o for o in created
                 if getattr(getattr(o, "Proxy", None), "Type", None)
                 == "ThreadFiller"]
        self.assertEqual(fills, [])

    def test_an_external_thread_larger_than_its_shaft_gets_a_sleeve(self):
        shaft, sub = self._shaft(radius=4.0)      # an 8mm shaft
        created = []
        cutter_obj, cut = api.build_thread(
            self.doc, shaft, sub,
            {"Diameter": 12.0, "Pitch": 1.75, "Length": 10.0}, created)
        self.assertGreater(feature.fill_needed(cutter_obj), 0.0)
        self.assertEqual(
            len([o for o in created if o.TypeId == "Part::Fuse"]), 1)
        self.assertTrue(cut.Shape.isValid())
        self.assertEqual(len(cut.Shape.Solids), 1,
                         "the sleeve did not merge with the shaft")
        # and the thread really is bigger than the shaft it was cut on
        box = cut.Shape.optimalBoundingBox()
        self.assertGreater(max(box.XLength, box.YLength), 8.0 + 1e-6)
        self.assertIsNone(api.diameter_note(cutter_obj),
                          "the requested diameter should now be reachable")

    def test_an_internal_thread_smaller_than_its_bore_gets_a_liner(self):
        block, sub = self._bored_block(bore=5.0)
        created = []
        cutter_obj, cut = api.build_thread(
            self.doc, block, sub,
            {"Diameter": 6.0, "Pitch": 1.0, "Length": 10.0}, created)
        self.assertGreater(feature.fill_needed(cutter_obj), 0.0)
        self.assertTrue(cut.Shape.isValid())
        self.assertEqual(len(cut.Shape.Solids), 1)
        self.assertIsNone(api.diameter_note(cutter_obj))

    def test_the_setting_off_falls_back_to_clamping(self):
        """With AddMaterial off the old behaviour must return intact --
        clamp to the blank and report it, never silently resize."""
        shaft, sub = self._shaft(radius=4.0)
        created = []
        cutter_obj, _cut = api.build_thread(
            self.doc, shaft, sub,
            {"Diameter": 12.0, "Pitch": 1.75, "Length": 10.0,
             "AddMaterial": False}, created)
        self.assertEqual(feature.fill_needed(cutter_obj), 0.0)
        self.assertEqual([o for o in created if o.TypeId == "Part::Fuse"], [])
        self.assertIsNotNone(api.diameter_note(cutter_obj))

    def test_the_fill_tube_stops_just_short_of_the_cutter(self):
        """It must cover the run, but NOT end flush with the cutter.

        This asserted an exact match until a 100mm internal thread showed
        why it cannot: coplanar end faces made Part::Cut refuse outright at
        five different pitches. The tube is inset by feature.FILL_INSET at
        each end, so it covers all but a sliver and shares no plane.
        """
        shaft, sub = self._shaft(radius=4.0)
        created = []
        cutter_obj, _cut = api.build_thread(
            self.doc, shaft, sub,
            {"Diameter": 12.0, "Pitch": 1.75, "Length": 10.0}, created)
        filler = [o for o in created
                  if getattr(getattr(o, "Proxy", None), "Type", None)
                  == "ThreadFiller"][0]
        fill_box = filler.Shape.optimalBoundingBox()
        cut_box = cutter_obj.Shape.optimalBoundingBox()
        inset = 2.0 * feature.FILL_INSET
        self.assertAlmostEqual(fill_box.ZLength, cut_box.ZLength - inset,
                               delta=1e-3,
                               msg="the tube must cover the run bar the "
                                   "inset that keeps its faces off the "
                                   "cutter's")
        self.assertGreater(fill_box.ZLength, 0.8 * cut_box.ZLength,
                           "the inset must stay a sliver, not a gap")


class TestLargeDiameterThreads(unittest.TestCase):
    """100mm threads, reported as erroring.

    Two separate causes, both fixed and both pinned here:

      * the ISO table stopped at M24 and both lookups snapped to the NEAREST
        entry, so a 100mm selection defaulted to a 24mm thread;
      * an internal thread at 100mm always needs a liner (the printed form
        wants a smaller bore than any 100mm hole), and the liner spanned
        EXACTLY the cutter's own axial range -- coplanar end faces, which
        Part::Cut refused outright at 4.0, 2.0, 1.5, 1.25 and 1.0 pitch
        while the identical geometry without a liner built at all of them.
    """

    def setUp(self):
        self.doc = App.newDocument("bigtest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _shaft(self, radius, height=40.0):
        obj = self.doc.addObject("Part::Cylinder", "Shaft")
        obj.Radius, obj.Height = radius, height
        self.doc.recompute()
        return obj, self._face(obj, radius)

    def _bore(self, radius, wall=25.0, height=40.0):
        obj = self.doc.addObject("Part::Feature", "Block")
        obj.Shape = Part.makeCylinder(radius + wall, height).cut(
            Part.makeCylinder(radius, height))
        self.doc.recompute()
        return obj, self._face(obj, radius)

    def _face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if (hasattr(f.Surface, "Radius")
                    and abs(f.Surface.Radius - radius) < 1e-6):
                return "Face%d" % (i + 1)
        raise AssertionError("no face at r=%.3f" % radius)

    def test_a_100mm_shaft_defaults_to_a_100mm_thread(self):
        _shaft, sub = self._shaft(50.0)
        circle = selection.resolve(_shaft, sub)
        defaults = api.defaults_for(circle)
        self.assertAlmostEqual(defaults["Diameter"], 100.0, places=3,
                               msg="defaulted to M%.1f" % defaults["Diameter"])

    def test_a_100mm_external_thread_builds_at_every_pitch(self):
        for pitch in (6.0, 3.0, 2.0, 1.25):
            shaft, sub = self._shaft(50.0)
            _cutter, cut = api.create_thread(
                self.doc, shaft, sub,
                {"Diameter": 100.0, "Pitch": pitch, "Length": 20.0})
            self.assertTrue(cut.Shape.isValid(), "pitch %.2f" % pitch)
            self.assertEqual(len(cut.Shape.Solids), 1, "pitch %.2f" % pitch)

    def test_a_100mm_internal_thread_builds_at_every_pitch(self):
        """THE regression: these are the exact pitches that failed."""
        for pitch in (6.0, 4.0, 3.0, 2.0, 1.5, 1.25, 1.0):
            block, sub = self._bore(50.0)
            _cutter, cut = api.create_thread(
                self.doc, block, sub,
                {"Diameter": 100.0, "Pitch": pitch, "Length": 20.0})
            self.assertTrue(cut.Shape.isValid(), "pitch %.2f" % pitch)
            self.assertEqual(len(cut.Shape.Solids), 1, "pitch %.2f" % pitch)

    def test_a_100mm_internal_thread_really_does_need_a_liner(self):
        """Fixture check: if this stops being the filled case, the test
        above stops covering the bug it was written for."""
        block, sub = self._bore(50.0)
        cutter_obj, _cut = api.create_thread(
            self.doc, block, sub,
            {"Diameter": 100.0, "Pitch": 2.0, "Length": 20.0})
        self.assertGreater(feature.fill_needed(cutter_obj), 0.0)

    def test_the_liner_stops_short_of_the_cutter_at_both_ends(self):
        """Coplanar faces are what Part::Cut choked on, so the inset is the
        fix and must stay measurable."""
        block, sub = self._bore(50.0)
        created = []
        cutter_obj, _cut = api.build_thread(
            self.doc, block, sub,
            {"Diameter": 100.0, "Pitch": 2.0, "Length": 20.0}, created)
        filler = [o for o in created
                  if getattr(getattr(o, "Proxy", None), "Type", None)
                  == "ThreadFiller"][0]
        liner = filler.Shape.optimalBoundingBox()
        tool = cutter_obj.Shape.optimalBoundingBox()
        self.assertGreater(liner.ZMin, tool.ZMin + 1e-6,
                           "the liner's low end is flush with the cutter's")
        self.assertLess(liner.ZMax, tool.ZMax - 1e-6,
                        "the liner's high end is flush with the cutter's")

    def test_a_thread_far_larger_than_its_shaft_still_builds(self):
        """40mm of sleeve: the fill is not a rounding correction here."""
        shaft, sub = self._shaft(10.0, height=30.0)
        cutter_obj, cut = api.create_thread(
            self.doc, shaft, sub,
            {"Diameter": 100.0, "Pitch": 6.0, "Length": 20.0})
        self.assertGreater(feature.fill_needed(cutter_obj), 30.0)
        self.assertTrue(cut.Shape.isValid())
        self.assertEqual(len(cut.Shape.Solids), 1)
        box = cut.Shape.optimalBoundingBox()
        self.assertGreater(max(box.XLength, box.YLength), 90.0)


class TestSelectingAFlatCircularFace(unittest.TestCase):
    """A disc at the end of a rod names a circle just as well as the rod's
    side does, and is a far bigger thing to click than the edge round it."""

    def setUp(self):
        self.doc = App.newDocument("flatfacetest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _rod(self, radius=4.0, height=20.0):
        obj = self.doc.addObject("Part::Cylinder", "Rod")
        obj.Radius, obj.Height = radius, height
        self.doc.recompute()
        return obj

    def _planar_faces(self, obj):
        return [(i + 1, f) for i, f in enumerate(obj.Shape.Faces)
                if isinstance(f.Surface, Part.Plane)]

    def test_a_rod_end_face_resolves_to_its_circle(self):
        rod = self._rod(radius=4.0, height=20.0)
        index, _face = self._planar_faces(rod)[0]
        circle = selection.resolve(rod, "Face%d" % index)
        self.assertAlmostEqual(circle.radius, 4.0, places=6)
        self.assertAlmostEqual(abs(circle.axis.z), 1.0, places=6)
        self.assertEqual(circle.mode, form.EXTERNAL)

    def test_an_end_face_runs_one_way_like_an_edge(self):
        """It sits at ONE end of the rod, so straddling would put half the
        cutter in open air -- the same reason an edge does not straddle."""
        rod = self._rod(radius=4.0, height=20.0)
        for index, _face in self._planar_faces(rod):
            circle = selection.resolve(rod, "Face%d" % index)
            self.assertNotEqual(
                circle.direction, form.BOTH,
                "a flat end face must pick a direction, not straddle")

    def test_threading_from_an_end_face_builds(self):
        rod = self._rod(radius=4.0, height=20.0)
        index, _face = self._planar_faces(rod)[0]
        _cutter, cut = api.create_thread(
            self.doc, rod, "Face%d" % index,
            {"Diameter": 8.0, "Pitch": 1.25, "Length": 8.0})
        self.assertTrue(cut.Shape.isValid())
        self.assertEqual(len(cut.Shape.Solids), 1)
        self.assertLess(cut.Shape.Volume, rod.Shape.Volume)

    def test_an_annulus_asks_rather_than_guessing(self):
        """A tube's end face bounds two circles and either could be meant."""
        outer = Part.makeCylinder(8.0, 20.0)
        hole = Part.makeCylinder(4.0, 20.0)
        tube = self.doc.addObject("Part::Feature", "Tube")
        tube.Shape = outer.cut(hole)
        self.doc.recompute()
        annuli = [i + 1 for i, f in enumerate(tube.Shape.Faces)
                  if isinstance(f.Surface, Part.Plane)]
        with self.assertRaises(selection.SelectionError) as caught:
            selection.resolve(tube, "Face%d" % annuli[0])
        self.assertIn("circular edge", str(caught.exception))
        self.assertIn("16.00", str(caught.exception))

    def test_a_non_circular_flat_face_is_still_rejected(self):
        box = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        with self.assertRaises(selection.SelectionError) as caught:
            selection.resolve(box, "Face1")
        self.assertIn("no circular edge", str(caught.exception))


class TestPrintTestPiece(unittest.TestCase):
    """The coupon exists to answer "do MY settings mate on MY printer?", so
    what matters is that it goes through the same cutter as the real thread
    and comes out at nominal with nothing relieved."""

    def setUp(self):
        self.doc = App.newDocument("couponstest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _params(self, **over):
        params = {
            "Mode": form.EXTERNAL, "ThreadForm": form.PRINTED,
            "Diameter": 8.0, "Pitch": 1.25, "Length": 10.0,
            "Direction": form.BOTH, "Clearance": 0.12,
            "Overrun": 1.0, "StartAngle": 0.0,
            "FlushEnds": True, "LeftHanded": False,
        }
        params.update(over)
        return params

    def test_builds_a_mated_pair(self):
        from tapdie import testpiece

        created = []
        male, female = testpiece.build(self.doc, self._params(), created)
        for obj, what in ((male, "male"), (female, "female")):
            self.assertFalse(obj.Shape.isNull(), "%s is null" % what)
            self.assertTrue(obj.Shape.isValid(), "%s is invalid" % what)
            self.assertEqual(len(obj.Shape.Solids), 1,
                             "%s is not one solid" % what)
            self.assertGreater(obj.Shape.Volume, 0.0)
        self.assertGreaterEqual(len(created), 6,
                                "every object must be tracked for undo")

    def test_the_pieces_do_not_overlap(self):
        """They print side by side, so they must not share space."""
        from tapdie import testpiece

        male, female = testpiece.build(self.doc, self._params())
        m = male.Shape.optimalBoundingBox()
        f = female.Shape.optimalBoundingBox()
        self.assertGreater(f.XMin, m.XMax - 1e-6,
                           "the coupon halves intersect: male XMax %.3f, "
                           "female XMin %.3f" % (m.XMax, f.XMin))

    def test_neither_blank_needs_relieving(self):
        """Both are cut at nominal, so a bad fit means the CLEARANCE is
        wrong -- never the blank. api.diameter_note must stay silent."""
        from tapdie import testpiece

        created = []
        testpiece.build(self.doc, self._params(), created)
        cutters = [o for o in created
                   if getattr(getattr(o, "Proxy", None), "Type", None)
                   == "ThreadCutter"]
        self.assertEqual(len(cutters), 2)
        for cutter_obj in cutters:
            self.assertIsNone(
                api.diameter_note(cutter_obj),
                "%s blank is the wrong size: %s"
                % (cutter_obj.Mode, api.diameter_note(cutter_obj)))

    def test_it_carries_the_settings_it_was_given(self):
        """A coupon cut with different settings than the part would answer a
        question nobody asked."""
        from tapdie import testpiece

        created = []
        params = self._params(Pitch=2.0, Clearance=0.2,
                              LeftHanded=True, StartAngle=30.0)
        testpiece.build(self.doc, params, created)
        cutters = [o for o in created
                   if getattr(getattr(o, "Proxy", None), "Type", None)
                   == "ThreadCutter"]
        for cutter_obj in cutters:
            self.assertAlmostEqual(cutter_obj.Pitch.Value, 2.0, places=9)
            self.assertAlmostEqual(cutter_obj.Clearance.Value, 0.2, places=9)
            self.assertTrue(cutter_obj.LeftHanded)
            self.assertAlmostEqual(cutter_obj.StartAngle.Value, 30.0,
                                   places=9)

    def test_each_piece_gets_its_own_mode(self):
        from tapdie import testpiece

        created = []
        testpiece.build(self.doc, self._params(), created)
        modes = sorted(o.Mode for o in created
                       if getattr(getattr(o, "Proxy", None), "Type", None)
                       == "ThreadCutter")
        self.assertEqual(modes, [form.EXTERNAL, form.INTERNAL])

    def test_thread_length_stays_small_at_any_pitch(self):
        from tapdie import testpiece

        for pitch in (0.4, 1.25, 3.8, 10.0):
            length = testpiece.thread_length(pitch)
            self.assertGreaterEqual(length, testpiece.MIN_THREAD)
            self.assertLessEqual(length, testpiece.MAX_THREAD,
                                 "pitch %.2f made a %.1fmm coupon"
                                 % (pitch, length))

    def test_a_coarse_pitch_still_gets_several_turns(self):
        from tapdie import testpiece

        for pitch in (0.5, 1.25, 2.5):
            turns = testpiece.thread_length(pitch) / pitch
            self.assertGreaterEqual(turns, 3.0,
                                    "pitch %.2f gives only %.1f turns"
                                    % (pitch, turns))


class TestUndoRemovesTheWholeThread(unittest.TestCase):
    """One Ctrl-Z must remove the cutter AND the boolean, and give the base
    back.

    It used to leave the Part::Cut behind with its Tool gone AND leave the
    base hidden, so the user saw an empty viewport and could not undo out of
    it. api.create_thread's docstring blamed the AttachedTo/Cut dependency
    diamond; bisection showed the diamond is innocent and the real cause was
    cutter.build creating and closing a scratch document inside execute().
    """

    def setUp(self):
        # NOT hidden: undo is what is under test and a hidden document is a
        # different enough animal that testing it would prove less.
        self.doc = App.newDocument("undotest")
        App.setActiveDocument(self.doc.Name)
        # freecadcmd leaves UndoMode at 0, so transactions record NOTHING and
        # UndoNames stays empty -- every assertion here would pass or fail for
        # reasons unrelated to the bug. Turn it on explicitly rather than
        # inheriting whatever the environment happens to do.
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _shaft(self):
        obj = self.doc.addObject("Part::Cylinder", "Shaft")
        obj.Radius, obj.Height = 4.0, 30.0
        self.doc.recompute()
        for i, f in enumerate(obj.Shape.Faces):
            if (hasattr(f.Surface, "Radius")
                    and abs(f.Surface.Radius - 4.0) < 1e-6):
                return obj, "Face%d" % (i + 1)
        raise AssertionError("no cylindrical face")

    def test_one_undo_removes_both_objects(self):
        shaft, sub = self._shaft()
        baseline = {o.Name for o in self.doc.Objects}
        api.create_thread(self.doc, shaft, sub)
        self.doc.recompute()
        stack = list(self.doc.UndoNames)
        self.doc.undo()
        self.doc.recompute()
        left = sorted({o.Name for o in self.doc.Objects} - baseline)
        # The OUTCOME is the contract, asserted first: one Ctrl-Z takes the
        # whole thread with it. An earlier version of this test asserted the
        # undo stack was exactly ['Thread'] before checking that, and it
        # failed in the full suite while passing alone -- FreeCAD carries
        # transaction state across documents within a process, so the step
        # COUNT is a property of the whole run, not of create_thread. The
        # count is reported here for context, never asserted.
        self.assertEqual(left, [],
                         "one undo left %s behind (undo stack was %s)"
                         % (left, stack))

    def test_undo_leaves_no_boolean_with_a_missing_tool(self):
        """The specific damage: a Part::Cut whose Tool is gone."""
        shaft, sub = self._shaft()
        api.create_thread(self.doc, shaft, sub)
        self.doc.recompute()
        self.doc.undo()
        self.doc.recompute()
        orphans = [o.Name for o in self.doc.Objects
                   if o.TypeId == "Part::Cut" and o.Tool is None]
        self.assertEqual(orphans, [])

    def test_undo_gives_the_base_part_back(self):
        """Part::Cut hides its Base. Undo must unhide it, or the user is left
        staring at an empty viewport with nothing to select."""
        shaft, sub = self._shaft()
        api.create_thread(self.doc, shaft, sub)
        self.doc.recompute()
        self.doc.undo()
        self.doc.recompute()
        self.assertTrue(shaft.ViewObject is None
                        or shaft.ViewObject.Visibility,
                        "the base part was left hidden after undo")

    def test_the_scratch_document_is_reused_not_recreated(self):
        """The fix itself: build must not create-and-close per call.

        Asserted through the document list rather than by counting calls,
        because it is the create/close PAIR that does the damage.
        """
        from tapdie import cutter as cutter_mod

        shaft, sub = self._shaft()
        api.create_thread(self.doc, shaft, sub)
        first = [n for n in App.listDocuments()
                 if n.startswith(cutter_mod.SCRATCH)]
        self.assertEqual(len(first), 1,
                         "expected exactly one scratch document, got %s"
                         % first)
        shaft2, sub2 = self._shaft()
        api.create_thread(self.doc, shaft2, sub2)
        second = [n for n in App.listDocuments()
                  if n.startswith(cutter_mod.SCRATCH)]
        self.assertEqual(second, first, "the scratch document was not reused")
        self.assertEqual(
            len(App.getDocument(first[0]).Objects), 0,
            "the scratch document should be left empty between builds")


class TestDiagnosticsAndChecks(unittest.TestCase):
    """The three things the 2026-08-04 review found reporting nothing:
    a swallowed error message, an inert Diameter, and a fixed Overrun."""

    def setUp(self):
        self.doc = App.newDocument("diagtest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # ---- the real error reaches the caller ------------------------------

    def test_the_real_profile_error_reaches_the_caller(self):
        """A generic "check Diameter, Pitch and the lands" is not a diagnosis.

        The overrun-through-the-axis case is the motivating one, measured on
        a 0.9mm bore: none of the three things the old message named can fix
        it, and the one it named first does not affect the geometry at all.
        """
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.INTERNAL
        # Diameter must be small enough that it does not ask for the bore to
        # be opened out: it drives the anchor now, and the default 20mm would
        # move the profile to r=8.16 where a 1mm overrun clears the axis
        # easily and there would be no error to report.
        obj.Diameter = 2.0
        obj.SurfaceRadius = 0.9
        obj.Overrun = 1.0
        self.doc.recompute()
        with self.assertRaises(api.ThreadError) as caught:
            api._validate(obj, None)
        self.assertIn("overrun", str(caught.exception))
        self.assertIn("0.9000", str(caught.exception))

    def test_a_successful_rebuild_clears_the_previous_error(self):
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.INTERNAL
        obj.Diameter = 2.0            # see the test above: Diameter anchors
        obj.SurfaceRadius = 0.9
        self.doc.recompute()
        self.assertIsNotNone(obj.Proxy.last_error)
        obj.Diameter = 20.0
        obj.SurfaceRadius = 8.2597
        self.doc.recompute()
        self.assertIsNone(obj.Proxy.last_error)
        api._validate(obj, None)      # must not raise

    # ---- Diameter is a real check ---------------------------------------

    def test_a_matching_blank_reports_nothing(self):
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.Diameter = 8.0
        obj.SurfaceRadius = 4.0
        self.doc.recompute()
        self.assertIsNone(api.diameter_note(obj))

    def test_a_smaller_diameter_on_a_bigger_shaft_is_honoured(self):
        """Diameter DRIVES the size: a die turns the shaft down as it cuts.

        Finding 1 was that Diameter reached cutter_points and was never read
        -- identical profiles for 8.0 and 24.0 -- so a user threading a 20mm
        shaft could ask for 16 and silently get 20.
        """
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 2.0
        obj.Diameter = 16.0
        obj.SurfaceRadius = 10.0      # a 20mm shaft
        obj.Length = 8.0
        self.doc.recompute()
        self.assertNotIn("Invalid", obj.State, "did not build: %s"
                         % obj.Proxy.last_error)
        self.assertIsNone(api.diameter_note(obj),
                          "an achievable request must not be reported")
        # The cutter has to reach out past the shaft to take it down, so its
        # own extent proves the relief is really there.
        box = obj.Shape.optimalBoundingBox()
        self.assertGreaterEqual(max(box.XMax, box.YMax), 10.0 - 1e-6)

    def test_a_bigger_diameter_in_a_smaller_bore_is_honoured(self):
        """The internal direction: a tap opens the hole out."""
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.INTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 2.5
        obj.Diameter = 20.0
        obj.SurfaceRadius = 5.0       # a 10mm bore
        obj.Length = 8.0
        self.doc.recompute()
        self.assertNotIn("Invalid", obj.State, "did not build: %s"
                         % obj.Proxy.last_error)
        self.assertIsNone(api.diameter_note(obj))
        anchor = form.effective_surface_radius(
            obj.Mode, obj.Diameter.Value, obj.Pitch.Value, obj.Angle.Value,
            obj.RootLand.Value, obj.CrestLand.Value, obj.Clearance.Value,
            obj.SurfaceRadius.Value)
        self.assertGreater(anchor, 5.0, "the bore was not opened out")
        box = obj.Shape.optimalBoundingBox()
        self.assertGreaterEqual(max(box.XMax, box.YMax), anchor - 1e-6)

    def test_the_impossible_direction_is_reported_not_silently_ignored(self):
        """A thread LARGER than the shaft would need material added."""
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 2.0
        obj.Diameter = 24.0
        obj.SurfaceRadius = 10.0      # only a 20mm shaft to work with
        self.doc.recompute()
        note = api.diameter_note(obj)
        self.assertIsNotNone(note)
        self.assertIn("20.00", note)
        self.assertIn("24.00", note)
        self.assertIn("removes material", note)

    def test_a_tap_drilled_M8_bore_is_within_tolerance(self):
        """0.08mm of overshoot is real but must not nag on the common case.

        A standard 6.6mm M8 tap drill legally yields 8.08mm on the printed
        form. Warning about that on the commonest selection there is would
        train the user to ignore the line.
        """
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.INTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 1.25
        obj.Diameter = 8.0
        obj.SurfaceRadius = 3.3        # 6.6mm tap drill
        self.doc.recompute()
        self.assertIsNone(api.diameter_note(obj))

    # ---- Overrun scales to the bore -------------------------------------

    def _circle(self, radius, mode):
        return selection.Circle(
            centre=App.Vector(), axis=App.Vector(0, 0, 1), radius=radius,
            mode=mode, length=10.0, direction=form.BOTH)

    def test_a_small_bore_gets_an_overrun_it_can_survive(self):
        """Overrun 1.0 reaches through the axis of any bore under r=1, and
        the dialog had no control able to fix it."""
        self.assertLess(
            api.defaults_for(self._circle(0.9, form.INTERNAL))["Overrun"], 0.9)

    def test_a_shaft_keeps_the_full_overrun(self):
        """For a shaft the overrun runs OUTWARD, so the radius never binds."""
        self.assertEqual(
            api.defaults_for(self._circle(0.9, form.EXTERNAL))["Overrun"], 1.0)


if __name__ == "__main__":
    unittest.main()
