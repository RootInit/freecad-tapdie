"""The ThreadCutter parametric object.

Holds the parameters and produces the cutter solid.  It never performs the
boolean -- that is a native Part::Cut, so FreeCAD owns it.
"""

import math

import FreeCAD as App

from . import cutter, form, presets

ICON = "tapdie_cutter.svg"


class ThreadCutter(object):
    """Proxy for a Part::FeaturePython carrying a helical cutter solid."""

    def __init__(self, obj):
        self.Type = "ThreadCutter"
        self.add_properties(obj)
        obj.Proxy = self

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
            defaults = presets.form_defaults(obj.ThreadForm)
            obj.Angle = defaults["angle"]
            obj.RootLand = defaults["root_fraction"] * obj.Pitch.Value
            obj.CrestLand = defaults["crest_fraction"] * obj.Pitch.Value
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
        shape = cutter.build(points, obj.Pitch.Value, height,
                             left_handed=obj.LeftHanded)

        # Shape.translate()/.rotate() only set the shape's Location; assigning
        # obj.Shape re-syncs that Location to the object's CURRENT Placement
        # (identity, at this point), silently discarding the move. Bake the
        # transform into the geometry itself with transformGeometry() instead,
        # which survives the assignment below.
        move = App.Matrix()
        move.move(App.Vector(0, 0, -obj.Pitch.Value))
        shape = shape.transformGeometry(move)

        if obj.Reversed:
            # 180 deg about X is a proper rotation, so the helix keeps its
            # handedness while running the other way along the axis.
            spin = App.Matrix()
            spin.rotateX(math.radians(180.0))
            shape = shape.transformGeometry(spin)

        obj.Shape = shape

        # Part::Cut keeps Base and Tool placements independent, so the cutter
        # has to follow the base itself.  Composing placements is correct under
        # rotation as well as translation; assigning obj.Shape resets Placement,
        # so this must come after it.
        if obj.AttachedTo is not None:
            obj.Placement = obj.AttachedTo.Placement.multiply(
                obj.LocalPlacement)


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
