"""Build the swept cutter solid.

The sweep is done by a PartDesign AdditiveHelix used as the BASE feature of a
Body, inside a hidden scratch document.  The Body's shape is then the swept
solid itself -- nothing to subtract, nothing to infer -- and a copy of it
survives closing the document.

PartDesign is a document object type, not a GUI workbench, so none of this
requires a GUI or an active workbench.  The obvious alternative,
Part.BRepOffsetAPI.MakePipeShell over Part.makeLongHelix, was tested across 12
configurations during design and distorted the profile in every one: flank
angles of 38-60 degrees where 45 or 30 was wanted, and radii off by up to
1.1 mm, all while reporting a valid single solid.  Do not reintroduce it.
"""

import FreeCAD as App
import Part
import Sketcher

SCRATCH = "tapdie_scratch"

XZ_PLANE = 4      # index into Body.Origin.OriginFeatures
Z_AXIS = 2


class CutterError(Exception):
    """The sweep did not produce a usable solid."""


def build(points, pitch, height, left_handed=False):
    """Sweep `points` (radius, axial) into a helical solid.

    Returns a Part.Shape detached from any document.
    """
    if len(points) < 3:
        raise CutterError("a cutter profile needs at least 3 corners")
    if pitch <= 0.0 or height <= 0.0:
        raise CutterError("pitch and height must both be positive")

    doc = App.newDocument(SCRATCH, hidden=True)
    try:
        body = doc.addObject("PartDesign::Body", "Cutter")
        sketch = doc.addObject("Sketcher::SketchObject", "Profile")
        body.addObject(sketch)
        sketch.AttachmentSupport = [(body.Origin.OriginFeatures[XZ_PLANE], "")]
        sketch.MapMode = "FlatFace"

        # A sketch attached FlatFace to XZ maps (u, v) -> global (X, 0, Z), so
        # u is a radius and v an axial position.
        n = len(points)
        for i in range(n):
            a, b = points[i], points[(i + 1) % n]
            sketch.addGeometry(
                Part.LineSegment(App.Vector(a[0], a[1], 0),
                                 App.Vector(b[0], b[1], 0)), False)
        for i in range(n):
            sketch.addConstraint(
                Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))

        helix = doc.addObject("PartDesign::AdditiveHelix", "Helix")
        body.addObject(helix)
        helix.Profile = sketch
        helix.ReferenceAxis = (body.Origin.OriginFeatures[Z_AXIS], [""])
        helix.Mode = 0                  # pitch and height
        helix.Pitch = pitch
        helix.Height = height
        helix.Angle = 0.0
        helix.LeftHanded = bool(left_handed)

        doc.recompute()

        if "Up-to-date" not in helix.State:
            raise CutterError("helix did not recompute: %s" % helix.State)

        shape = body.Shape.copy()
        if not shape.isValid():
            raise CutterError("swept cutter is not a valid solid")
        if len(shape.Solids) != 1:
            raise CutterError(
                "swept cutter has %d solids, expected 1" % len(shape.Solids))
        if shape.Volume <= 0.0:
            raise CutterError("swept cutter has no volume")
        return shape
    finally:
        App.closeDocument(doc.Name)
