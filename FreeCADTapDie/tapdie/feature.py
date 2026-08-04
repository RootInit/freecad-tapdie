"""The ThreadCutter parametric object.

Holds the parameters and produces the cutter solid.  It never performs the
boolean -- that is a native Part::Cut, so FreeCAD owns it.
"""

import FreeCAD as App
import Part

from . import cutter, form, presets

ICON = "tapdie_cutter.svg"

# Free/abutting end detection: how far past each end plane (as a fraction of
# Pitch, tried at more than one scale so a single degenerate probe -- landing
# exactly on a face or a corner edge -- cannot flip the result) to probe for
# adjacent material. Any disagreement between scales, or an error evaluating
# isInside, is treated as the SAFE reading (abutting/clamped): gouging into a
# neighbouring feature is destructive, while a missing overrun merely leaves
# a plain collar the mating crest can jam against -- unwanted, but not
# destructive. See _detect_free_ends below.
END_PROBE_FRACTIONS = (0.05, 0.01)
MIN_END_PROBE = 1e-3


def feature_span(obj):
    """(z_lo, z_hi) of the threaded run in the anchor's own coordinates."""
    return form.span(obj.Direction, obj.Length.Value)


def _end_is_free(base_shape, anchor, surface_radius, pitch, z_edge, sign):
    """True if no material sits just past one end of the threaded run.

    `anchor` is the world Placement of the selected circle's centre/axis
    (AttachedTo.Placement * LocalPlacement -- the same frame api.py's
    local_frame() inverts to build LocalPlacement in the first place, so
    this is exactly circle.centre/circle.axis in world space). `z_edge` is
    the end's axial position relative to that anchor (+-Length/2); `sign`
    is which direction is "further past the end" (-1 for the low-z end,
    +1 for the high-z end).
    """
    results = []
    for frac in END_PROBE_FRACTIONS:
        eps = max(pitch * frac, MIN_END_PROBE)
        point_local = App.Vector(surface_radius, 0.0, z_edge + sign * eps)
        world_point = anchor.multVec(point_local)
        try:
            # checkFace=True: required, exactly as in selection.detect_mode --
            # without it a probe that happens to land on a flat end face
            # reads False/False and gives no signal at all.
            results.append(base_shape.isInside(world_point, 1e-7, True))
        except Exception:
            return False   # cannot evaluate -> SAFE (treat as abutting)
    if len(set(results)) != 1:
        return False       # scales disagree -> SAFE (treat as abutting)
    return not results[0]  # free means NO material just past the end


def _detect_free_ends(obj):
    """Per end of the threaded run: free (open space) or abutting (adjacent
    material)?  Returns (near_free, far_free) for the low/high z ends of the
    run, in the anchor's coordinates.

    Since the sweep is now placed by translation only -- Direction chooses
    WHERE the run sits, and no longer by the 180 degree rotation the old
    Reversed used -- the cutter's builder-frame low end always maps to the
    run's low end, so "near" and "far" mean the same thing in both frames.

    No base to check against -- an unattached ThreadCutter, which is how
    most of this module's own unit tests build one -- keeps today's
    behaviour: both ends free, matching every case before this detection
    existed.
    """
    base = getattr(obj, "AttachedTo", None)
    if base is None:
        # Nothing to gouge: an unattached ThreadCutter -- which is how most of
        # this module's own unit tests build one -- keeps the behaviour that
        # predates this detection.
        return True, True
    # From here there IS a base. Anything about it we cannot measure must read
    # as ABUTTING, matching _end_is_free's policy and the module docstring
    # above. This used to return the free reading, which is the destructive
    # direction: it lets the overrun cut into material we merely failed to
    # see. CLAUDE.md's rule for isInside probes -- audit BOTH directions,
    # because the one that fails open passes silently while the tool eats the
    # part -- applies to the callers of a probe as much as to the probe.
    try:
        base_shape = base.Shape
    except Exception:
        return False, False
    if base_shape is None or base_shape.isNull():
        return False, False

    anchor = base.Placement.multiply(obj.LocalPlacement)
    surface_radius = obj.SurfaceRadius.Value
    pitch = obj.Pitch.Value
    z_lo, z_hi = feature_span(obj)

    near_free = _end_is_free(base_shape, anchor, surface_radius, pitch,
                             z_lo, -1)
    far_free = _end_is_free(base_shape, anchor, surface_radius, pitch,
                            z_hi, 1)
    return near_free, far_free


class ThreadCutter(object):
    """Proxy for a Part::FeaturePython carrying a helical cutter solid."""

    def __init__(self, obj):
        self.Type = "ThreadCutter"
        # Set before add_properties: assigning a property fires onChanged,
        # which can reach execute() on some paths, and _check_recomputed
        # reads this attribute unconditionally.
        self.last_error = None
        self.add_properties(obj)
        obj.Proxy = self
        # _apply_preset only runs reactively from onChanged; nothing fires it
        # on a fresh object, so ThreadForm's default preset (Printed 90) would
        # otherwise leave Angle/RootLand/CrestLand unlocked despite a preset
        # being in effect. Apply it once, now that the properties exist and
        # Proxy is set.
        self._apply_preset(obj)

    def add_properties(self, obj):
        p = obj.addProperty
        if not hasattr(obj, "Mode"):
            p("App::PropertyEnumeration", "Mode", "Thread",
              "Internal cuts outward from a bore; external cuts inward from "
              "an OD")
            obj.Mode = [form.INTERNAL, form.EXTERNAL]
            obj.Mode = form.INTERNAL
        if not hasattr(obj, "ThreadForm"):
            p("App::PropertyEnumeration", "ThreadForm", "Thread",
              "Preset profile; Custom unlocks angle and land")
            obj.ThreadForm = list(form.FORMS)
            obj.ThreadForm = form.PRINTED
        if not hasattr(obj, "Diameter"):
            p("App::PropertyLength", "Diameter", "Thread",
              "Nominal major diameter of the thread")
            obj.Diameter = 20.0
        if not hasattr(obj, "Pitch"):
            p("App::PropertyLength", "Pitch", "Thread", "Thread pitch")
            obj.Pitch = 3.8
        if not hasattr(obj, "Angle"):
            p("App::PropertyAngle", "Angle", "Thread",
              "Included angle; overhang when printed upright is 90 - angle/2")
            obj.Angle = 90.0
        if not hasattr(obj, "RootLand"):
            p("App::PropertyLength", "RootLand", "Thread",
              "Flat at the bottom of the groove (the thread's root)")
            obj.RootLand = 0.08
        if not hasattr(obj, "CrestLand"):
            p("App::PropertyLength", "CrestLand", "Thread",
              "Flat left on the surface between grooves (the crest)")
            obj.CrestLand = 0.08
        if not hasattr(obj, "Clearance"):
            p("App::PropertyLength", "Clearance", "Fit",
              "Gap normal to the flanks")
            obj.Clearance = 0.12
        if not hasattr(obj, "Length"):
            p("App::PropertyLength", "Length", "Extent", "Threaded length")
            obj.Length = 15.2
        if not hasattr(obj, "SurfaceRadius"):
            p("App::PropertyLength", "SurfaceRadius", "Extent",
              "Radius of the cylindrical surface being threaded")
            obj.SurfaceRadius = 8.2597
        if not hasattr(obj, "Overrun"):
            p("App::PropertyLength", "Overrun", "Extent",
              "How far the cutter's parallel section runs past the surface")
            obj.Overrun = 1.0
        if not hasattr(obj, "StartAngle"):
            p("App::PropertyAngle", "StartAngle", "Thread",
              "Angular position of the thread start, for lining a thread up "
              "with something else. An internal thread is ALREADY clocked "
              "half a pitch (180 deg) round from an external one, so a nut "
              "and bolt cut with the same settings mate as they stand; this "
              "is your adjustment on top of that, and means the same thing "
              "in both modes")
            obj.StartAngle = 0.0
        if not hasattr(obj, "LeftHanded"):
            p("App::PropertyBool", "LeftHanded", "Thread", "Left-hand thread")
            obj.LeftHanded = False
        if not hasattr(obj, "Direction"):
            p("App::PropertyEnumeration", "Direction", "Extent",
              "Which way the run travels from the selected circle. 'Both "
              "ways' straddles it -- right for a cylindrical face, wrong for "
              "an edge at the end of a rod, where half the cutter lands in "
              "open air")
            obj.Direction = list(form.DIRECTIONS)
            obj.Direction = form.BOTH
        if not hasattr(obj, "AttachedTo"):
            p("App::PropertyLink", "AttachedTo", "Base",
              "Part this cutter follows, so the thread stays with it when it "
              "moves")
        if not hasattr(obj, "LocalPlacement"):
            p("App::PropertyPlacement", "LocalPlacement", "Base",
              "Cutter frame in the base part's local coordinates")
        if not hasattr(obj, "FlushEnds"):
            p("App::PropertyBool", "FlushEnds", "Extent",
              "Face the cutter off flat at the ends of the run, instead of "
              "letting it overrun a pitch past them. An end that abuts "
              "adjacent material is always faced off, regardless")
            obj.FlushEnds = True
        if not hasattr(obj, "LeadIn"):
            p("App::PropertyBool", "LeadIn", "LeadIn",
              "Relieve the first turn at each FREE end with a 45 degree "
              "chamfer; an end abutting adjacent material never gets one, "
              "regardless of this setting")
            obj.LeadIn = True
        if not hasattr(obj, "NearEndFree"):
            p("App::PropertyBool", "NearEndFree", "LeadIn",
              "Read-only. Whether the low-z end of the swept cutter "
              "(builder frame, not necessarily the physical near end) was "
              "found free of adjacent material -- and so gets its overrun "
              "and lead-in chamfer")
            obj.NearEndFree = True
            obj.setEditorMode("NearEndFree", 1)   # read-only
        if not hasattr(obj, "FarEndFree"):
            p("App::PropertyBool", "FarEndFree", "LeadIn",
              "Read-only. The same detection for the high-z end")
            obj.FarEndFree = True
            obj.setEditorMode("FarEndFree", 1)    # read-only

    def onDocumentRestored(self, obj):
        # A proxy restored from a saved file did not run __init__, so it has
        # no last_error; api._check_recomputed would then read the attribute
        # off a restored object and raise AttributeError instead of the
        # ThreadError it exists to raise.
        if not hasattr(self, "last_error"):
            self.last_error = None
        self.add_properties(obj)

    def _apply_preset(self, obj):
        """Presets drive angle and land; Custom hands them back to the user."""
        locked = 1 if obj.ThreadForm != form.CUSTOM else 0
        if obj.ThreadForm != form.CUSTOM:
            # form_defaults needs Pitch now: the printed form's land is
            # floored at one extrusion width, an ABSOLUTE width, not a pure
            # fraction of pitch (see presets.py for why a pure fraction
            # collapses to a knife edge at a fine pitch).
            defaults = presets.form_defaults(obj.ThreadForm, obj.Pitch.Value,
                                             obj.Mode)
            obj.Angle = defaults["angle"]
            obj.RootLand = defaults["root_land"]
            obj.CrestLand = defaults["crest_land"]
        obj.setEditorMode("Angle", locked)
        obj.setEditorMode("RootLand", locked)
        obj.setEditorMode("CrestLand", locked)

    def onChanged(self, obj, prop):
        # Mode belongs here too: ISO's two truncations swap between internal
        # and external, so flipping Mode changes which land is which.
        if prop in ("ThreadForm", "Pitch", "Mode") and hasattr(obj, "Angle"):
            self._apply_preset(obj)

    def execute(self, obj):
        # RECORD WHAT WENT WRONG ON THE WAY PAST.
        #
        # FreeCAD swallows whatever execute() raises: it marks the object
        # Invalid and writes the traceback to the Report view, and the
        # exception never reaches doc.recompute()'s caller. api._validate
        # therefore had nothing but obj.State to go on and had to GUESS at a
        # cause -- it told a user whose 0.9mm bore was smaller than the 1.0mm
        # Overrun to "check Diameter, Pitch and the lands", none of which can
        # fix that, and the first of which does not affect the geometry at
        # all. The real message ("cutter overrun 1.0000 reaches through the
        # axis from a bore at r=0.9000") existed the whole time and was
        # thrown away.
        try:
            self._build_shape(obj)
        except Exception as exc:
            self.last_error = str(exc)
            raise
        self.last_error = None

    def _build_shape(self, obj):
        # DIAMETER DRIVES THE SIZE; the blank only says where to start.
        #
        # The profile is anchored on a surface, not on a nominal size, so
        # asking for a thread the blank does not already suit means reaching
        # further: a die turns the shaft down before it cuts, a tap opens the
        # bore out. That is exactly what the crest-relief shell already does
        # for clearance, so honouring Diameter is the same mechanism with a
        # bigger gap to bridge. Anchor the profile at the radius the
        # requested diameter needs, and let the relief span from the real
        # surface to it.
        #
        # Only one direction is physically available in each mode -- smaller
        # for external, larger for internal -- and effective_surface_radius
        # raises for the other, because no cutting tool adds material.
        surface = obj.SurfaceRadius.Value
        anchor = form.effective_surface_radius(
            obj.Mode, obj.Diameter.Value, obj.Pitch.Value, obj.Angle.Value,
            obj.RootLand.Value, obj.CrestLand.Value, obj.Clearance.Value,
            surface)
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value,
            anchor, obj.Overrun.Value)

        # Overrun a whole pitch at each end: a groove that stops at the face
        # leaves a collar of plain surface for the mating crest to jam on.
        pitch_v = obj.Pitch.Value
        length_v = obj.Length.Value
        height = length_v + 2.0 * pitch_v
        shape = cutter.build(points, pitch_v, height,
                             left_handed=obj.LeftHanded)

        # The overrun above is only correct at a FREE end. Where the
        # threaded run instead butts against adjacent material (a shoulder,
        # a hex head, a blind bore's floor), that same overrun gouges
        # straight into it -- measured 48.5915 mm3 cut out of a hex head on
        # the fixture that first surfaced this. Decide per end via the same
        # isInside-probe technique selection.py uses for internal/external
        # detection, just applied axially past each end instead of radially
        # across the surface, then clamp the sweep to the feature's own
        # plane on any end found abutting (and never chamfer that end --
        # a chamfer into a shoulder is useless: nothing can start a nut from
        # that end, and it only wastes engagement).
        near_free, far_free = _detect_free_ends(obj)
        obj.NearEndFree = near_free
        obj.FarEndFree = far_free

        # FACE THE ENDS OFF FLAT.
        #
        # The sweep is deliberately built a pitch longer than the run at each
        # end -- sweeping exactly to length leaves the crest dying out short
        # of the end face, which is why printed_threads sweeps past and faces
        # off flat. FlushEnds is the "faces off flat" half: it trims the
        # cutter back to the run's own extent, so the tool ends on a plane
        # perpendicular to the axis instead of on a partial turn hanging a
        # pitch past the part.
        #
        # An ABUTTING end is trimmed whatever FlushEnds says. That is not a
        # style choice: the overrun gouges straight into whatever it butts
        # against -- 48.5915 mm3 measured out of a hex head on the fixture
        # that first surfaced it.
        feature_lo, feature_hi = pitch_v, pitch_v + length_v
        flush = obj.FlushEnds
        z_keep_lo = feature_lo if (flush or not near_free) else 0.0
        z_keep_hi = feature_hi if (flush or not far_free) else height
        if z_keep_lo > 0.0 or z_keep_hi < height:
            radius_reach = max(pt[0] for pt in points)
            shape = cutter.clip_to_axial_range(shape, z_keep_lo, z_keep_hi,
                                               radius_reach)

        # Lead-in relief: a thread cut straight to a FREE face leaves a
        # sharp, fragile, hard-to-start first turn. At each FREE end (only),
        # fuse in a 45 degree chamfer -- fixed, independent of the thread's
        # own included angle -- wide at the feature's own end plane and
        # tapering back to the plain surface radius moving into the
        # material. cutter.lead_in_cone builds it as a revolved profile (one
        # construction for both Mode values -- see its docstring for why an
        # internal/external special-case used to exist here and was retired
        # after it failed to fuse at ordinary dimensions).
        #
        # THE CONES ARE CLAMPED TO THE SAME RANGE AS THE SWEEP. A cone's
        # axial reach EQUALS its radial depth, because it is 45 degrees --
        # so on a run shorter than cut_depth + radial_offset it crosses the
        # OPPOSITE end plane. This comment used to assert the reverse ("the
        # chamfer sits entirely within [feature_lo, feature_hi]"), untested,
        # and it was false: measured on a 4mm stub against an 8mm shoulder
        # with a 1mm run at pitch 3.8, the cutter reached z=-0.6959 and took
        # 0.3697mm out of the shoulder -- the very defect the abutting-end
        # clamp above exists to prevent, reintroduced by the feature added
        # after it. Where the run is long enough, which is every ordinary
        # case, the clip is a no-op.
        # Crest relief: clearance is radial, so the blank is taken down (or
        # out) to the crest radius over exactly the threaded run before the
        # profile's own groove is cut. Added to the same compound as
        # everything else -- Part::Cut removes every solid in the tool.
        # The relief spans from the REAL surface to the crest the ANCHOR
        # implies, so it removes both the clearance and whatever the
        # requested Diameter asked for on top. With a matching blank the two
        # radii coincide and this is the plain clearance shell as before.
        extras = []
        relief = cutter.crest_relief(
            obj.Mode,
            surface,
            form.crest_radius(obj.Mode, anchor,
                              obj.Clearance.Value, obj.Angle.Value),
            z_keep_lo, z_keep_hi, obj.Overrun.Value)
        if relief is not None:
            extras.append(relief)

        if obj.LeadIn and (near_free or far_free):
            tip_radius = points[0][0]
            reach = max(pt[0] for pt in points)
            if near_free:
                extras.append(cutter.clip_to_axial_range(
                    cutter.lead_in_cone(tip_radius, anchor,
                                        feature_lo, into_material=True),
                    z_keep_lo, z_keep_hi, reach))
            if far_free:
                extras.append(cutter.clip_to_axial_range(
                    cutter.lead_in_cone(tip_radius, anchor,
                                        feature_hi, into_material=False),
                    z_keep_lo, z_keep_hi, reach))

        if extras:
            # COMPOUND, not fuse.  A cutter carrying chamfers is legitimately
            # DISCONNECTED at some phases: whether the helix's last turn
            # reaches the chamfer plane depends on where the sweep's fractional
            # turn falls, so at some lengths a cone is a separate island.
            # Measured on M8x1.25, 4mm shaft, lengths 18.0..24.0 in 0.5 steps:
            # the fuse returns a VALID two-solid shape at exactly 19.5 and
            # 22.0 -- both 0.6 of a turn -- and one solid everywhere else.
            # The old `!= 1` check read that as a failure and refused to build
            # an otherwise perfectly good cutter.  removeSplitter() is worse
            # still: it returns an INVALID solid at 19.0, 21.5 and 24.0.
            #
            # A compound sidesteps all of it.  Part::Cut removes every solid in
            # the tool, connected or not, and building one needs no boolean at
            # all -- so there is no phase-dependent OCC behaviour left to trip
            # over.  Do not "tidy" this back into a fuse.
            shape = Part.makeCompound([shape] + extras)
            if not shape.isValid() or not shape.Solids:
                raise cutter.CutterError(
                    "cutter compound (helix + relief + chamfers) is invalid")

        # Do NOT transform the shape itself.  Shape.translate()/.rotate() only
        # set the shape's Location; assigning obj.Shape re-syncs that Location
        # to the object's CURRENT Placement (identity, at this point), so the
        # move is silently discarded the instant it is assigned below -- this
        # bit a previous version of this file.  Shape.transformGeometry() does
        # survive the assignment, but it rebuilds the geometry and converts
        # the two planar end caps into degree-(1,1) BSpline surfaces, which
        # reintroduces the BoundBox-on-trimmed-solid trap this project
        # documents (a rotated, offset case read a BoundBox 1mm off from the
        # true extent). Folding the same offset into Placement instead keeps
        # the shape's own geometry -- and its exact Part::GeomPlane end caps
        # -- untouched.
        # Place the run where Direction says, by TRANSLATION ONLY.
        #
        # The sweep occupies builder z in [0, height], and its nominal
        # threaded run -- excluding the pitch of overrun at each end -- is
        # [pitch, pitch + Length].  Shifting by -(pitch - z_lo) lands that
        # run on [z_lo, z_hi] in the anchor's coordinates, whatever
        # form.span() chose:
        #
        #     Both ways   [-L/2, +L/2]   straddles the selected circle
        #     Along axis  [0, +L]        starts at it, runs +axis
        #     Against     [-L, 0]        ends at it, runs -axis
        #
        # Getting the anchor wrong here has bitten before: the anchor api.py
        # binds is the SELECTED FACE'S MIDPOINT (selection.py computes it
        # that way on purpose -- see Task 5), not one end of it, so an early
        # version that shifted by a single pitch left half the bore unthreaded
        # and sent the rest of the cutter past the part's far face.
        #
        # The old Reversed used a 180-about-X rotation to run the other way
        # while staying on the same centred span. Direction supersedes it and
        # needs no rotation at all -- which is a real simplification, because
        # that rotation also flipped which physical end the builder frame's
        # "near" end meant, and _detect_free_ends had to carry a paragraph
        # explaining why it was nonetheless unaffected.
        # PHASE BY ROTATION ABOUT THE AXIS, not by an axial shift.
        #
        # A helix maps onto itself under a rotation combined with an axial
        # shift of the same fraction of a pitch, so either would clock the
        # thread -- but only the rotation leaves the run's axial extent
        # where Direction put it. Everything else in the cutter (the crest
        # relief, both lead-in cones, the flush end planes) is a solid of
        # revolution, so spinning the whole thing about Z moves the helical
        # groove and nothing else.
        #
        # The 180 degrees that makes an internal thread mate with an
        # external one lives in form.start_phase, not here.
        z_lo, _z_hi = form.span(obj.Direction, length_v)
        phase = form.start_phase(obj.Mode, obj.StartAngle.Value)
        offset = App.Placement(
            App.Vector(0, 0, z_lo - pitch_v),
            App.Rotation(App.Vector(0, 0, 1), phase))

        obj.Shape = shape        # untransformed

        # Part::Cut keeps Base and Tool placements independent, so the cutter
        # has to follow the base itself.  Composing placements is correct under
        # rotation as well as translation; assigning obj.Shape resets Placement,
        # so this must come after it.
        if obj.AttachedTo is not None:
            obj.Placement = obj.AttachedTo.Placement.multiply(
                obj.LocalPlacement).multiply(offset)
        else:
            obj.Placement = offset


class ThreadCutterViewProvider(object):
    """Draws the cutter as a translucent red tool, not as a part."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_cutter(doc, name="ThreadCutter"):
    """Create a ThreadCutter in `doc` and return it."""
    obj = doc.addObject("Part::FeaturePython", name)
    ThreadCutter(obj)
    if App.GuiUp:
        ThreadCutterViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.9, 0.2, 0.2)
        obj.ViewObject.Transparency = 60
    return obj
