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


def lead_in_cone(tip_radius, surface_radius, z_face, into_material):
    """A 45 degree relief chamfer at one end of the threaded run, built as a
    REVOLVED PROFILE, never a boolean between primitives.

    `tip_radius` is the profile's own most extreme radius -- the first of the
    six (radius, axial) points form.cutter_points returns, which for INTERNAL
    mode is the largest (the cutter's deepest reach, i.e. the thread's root:
    relieving out to it fully clears the first turn) and for EXTERNAL is the
    smallest (the thread's root again, just on the other side -- the
    narrowest point the tool reaches). Either way the chamfer tapers between
    `tip_radius` at `z_face` and `surface_radius` moving into the material
    along +Z (`into_material=True`) or -Z (`into_material=False`); 45 degrees
    is fixed here, independent of the thread's own included angle.

    A prior version built this as a cylinder-minus-cone boolean for EXTERNAL
    (a plain solid cone works for INTERNAL only, because a bore's
    pre-existing hollow core absorbs it, but a shaft has no such core --
    see git history). That boolean FAILED to fuse into a single solid at
    ordinary dimensions found by testing across a length sweep -- M8x1.25 on
    a 4mm shaft at Length=19.5 and 22.0mm, a narrow OCC tangency band, not an
    edge case. printed_threads builds every one of its lead-ins by revolving
    a closed polygon and never hits this class of failure, so that is what
    this does instead: the profile

        (tip_radius, z_face) -> (surface_radius, z_face)
        -> (surface_radius, z_face + depth*direction) -> close

    is a closed TRIANGLE in the (radius, axial) plane -- the horizontal edge
    is the full bevel at the face, the diagonal is the 45 degree cone
    surface, and the vertical edge (constant r=surface_radius) closes it
    back, tapering the wedge to zero width exactly at `depth`. Revolving
    that 360 degrees needs no boolean at all, so there is no tangency for
    OCC to go degenerate on.

    This ALSO retires the internal/external special-case entirely: the
    triangle only ever spans r in [surface_radius, tip_radius] (never
    touching the axis), so for INTERNAL it removes exactly the same
    material a full solid cone would have (the r < surface_radius portion
    of that cone was always coincident with the bore's own pre-existing
    hollow core, a no-op either way), and for EXTERNAL it never touches the
    shaft's solid core in the first place -- one construction, both modes.
    """
    depth = abs(tip_radius - surface_radius)
    if depth <= 0.0:
        raise CutterError(
            "lead-in chamfer has no depth to cut (tip radius equals surface "
            "radius)")
    dz = depth if into_material else -depth
    a = App.Vector(tip_radius, 0.0, z_face)
    b = App.Vector(surface_radius, 0.0, z_face)
    c = App.Vector(surface_radius, 0.0, z_face + dz)
    wire = Part.makePolygon([a, b, c, a])
    face = Part.Face(wire)
    solid = face.revolve(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 360.0)
    if not solid.isValid() or not solid.Solids:
        raise CutterError(
            "lead-in chamfer revolve produced an invalid solid")
    return solid


def clip_to_axial_range(shape, z_lo, z_hi, radius_reach):
    """Keep only the part of `shape` with builder-frame z in [z_lo, z_hi].

    Removes the pitch of sweep overrun at an end that abuts adjacent
    material -- left alone, that overrun gouges into it (see feature.py's
    free/abutting detection). The box is generously oversized in X/Y so only
    Z is ever the limiting bound; `radius_reach` just has to be at least the
    swept solid's own max radius, and a healthy margin is added on top.
    """
    if z_hi <= z_lo:
        raise CutterError(
            "clip range [%.4f, %.4f] is empty or inverted" % (z_lo, z_hi))
    margin = radius_reach * 4.0 + 10.0
    box = Part.makeBox(margin, margin, z_hi - z_lo,
                       App.Vector(-margin / 2.0, -margin / 2.0, z_lo))
    clipped = shape.common(box)
    if not clipped.isValid() or len(clipped.Solids) != 1:
        raise CutterError(
            "clipping the overrun to [%.4f, %.4f] produced an invalid or "
            "multi-solid cutter" % (z_lo, z_hi))
    return clipped
