"""The ThreadCutter parametric object.

Holds the parameters and produces the cutter solid.  It never performs the
boolean -- that is a native Part::Cut, so FreeCAD owns it.
"""

import FreeCAD as App

from . import cutter, form, presets

ICON = "tapdie_cutter.svg"


class ThreadCutter(object):
    """Proxy for a Part::FeaturePython carrying a helical cutter solid."""

    def __init__(self, obj):
        self.Type = "ThreadCutter"
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
        if not hasattr(obj, "LeftHanded"):
            p("App::PropertyBool", "LeftHanded", "Thread", "Left-hand thread")
            obj.LeftHanded = False
        if not hasattr(obj, "Reversed"):
            p("App::PropertyBool", "Reversed", "Extent",
              "Run the thread the other way along the axis from the selection")
            obj.Reversed = False
        if not hasattr(obj, "AttachedTo"):
            p("App::PropertyLink", "AttachedTo", "Base",
              "Part this cutter follows, so the thread stays with it when it "
              "moves")
        if not hasattr(obj, "LocalPlacement"):
            p("App::PropertyPlacement", "LocalPlacement", "Base",
              "Cutter frame in the base part's local coordinates")

    def onDocumentRestored(self, obj):
        self.add_properties(obj)

    def _apply_preset(self, obj):
        """Presets drive angle and land; Custom hands them back to the user."""
        locked = 1 if obj.ThreadForm != form.CUSTOM else 0
        if obj.ThreadForm != form.CUSTOM:
            # form_defaults needs Pitch now: the printed form's land is
            # floored at one extrusion width, an ABSOLUTE width, not a pure
            # fraction of pitch (see presets.py for why a pure fraction
            # collapses to a knife edge at a fine pitch).
            defaults = presets.form_defaults(obj.ThreadForm, obj.Pitch.Value)
            obj.Angle = defaults["angle"]
            obj.RootLand = defaults["root_land"]
            obj.CrestLand = defaults["crest_land"]
        obj.setEditorMode("Angle", locked)
        obj.setEditorMode("RootLand", locked)
        obj.setEditorMode("CrestLand", locked)

    def onChanged(self, obj, prop):
        if prop in ("ThreadForm", "Pitch") and hasattr(obj, "Angle"):
            self._apply_preset(obj)

    def execute(self, obj):
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
            obj.Clearance.Value,
            obj.SurfaceRadius.Value, obj.Overrun.Value)

        # Overrun a whole pitch at each end: a groove that stops at the face
        # leaves a collar of plain surface for the mating crest to jam on.
        height = obj.Length.Value + 2.0 * obj.Pitch.Value
        half = height / 2.0
        shape = cutter.build(points, obj.Pitch.Value, height,
                             left_handed=obj.LeftHanded)

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
        # Centre the sweep on LocalPlacement/AttachedTo rather than shifting
        # it by a single pitch.  The anchor api.py binds here is the
        # SELECTED FACE'S MIDPOINT (selection.py computes it that way on
        # purpose -- see Task 5), not one end of it, so a one-pitch offset
        # left the sweep starting at the anchor and running the full Length
        # from there: half the bore got no thread at all, and the far half
        # of the cutter sailed past the part's other face doing nothing.
        # Shifting by half the total swept height instead centres the run
        # on the anchor, so it reaches both ends symmetrically.  This is
        # also what keeps Reversed from walking the cutter off the part:
        # the 180-about-X rotation flips the sweep direction but must still
        # land on the same centred span, or a reversed cutter bound to a
        # real part would miss it entirely.
        if obj.Reversed:
            # 180 about X is a PROPER rotation, so the helix keeps its
            # handedness while running the other way along the axis.
            # Rotating the translation carries -half through to +half,
            # which is why the sign flips relative to the forward case.
            offset = App.Placement(App.Vector(0, 0, half),
                                   App.Rotation(App.Vector(1, 0, 0), 180.0))
        else:
            offset = App.Placement(App.Vector(0, 0, -half),
                                   App.Rotation())

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
