"""Build the swept cutter solid.

The sweep is done by a PartDesign AdditiveHelix used as the BASE feature of a
Body, inside a hidden scratch document.  The Body's shape is then the swept
solid itself -- nothing to subtract, nothing to infer -- and a copy of it
outlives the document's contents.

That scratch document is created ONCE and REUSED, never created and closed per
build.  See _scratch_document: doing both inside a feature's execute()
destroys the caller's open undo transaction.

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

from . import form

SCRATCH = "tapdie_scratch"

XZ_PLANE = 4      # index into Body.Origin.OriginFeatures
Z_AXIS = 2


class CutterError(Exception):
    """The sweep did not produce a usable solid."""


# The one scratch document, held across builds. A list rather than a plain
# global so it can be cleared and rebuilt without a `global` statement.
_SCRATCH_DOC = []


def _empty(doc):
    """Remove everything from the scratch document.

    Removing a PartDesign Body cascades to its Origin and its features, so a
    single pass over a list captured up front can leave objects behind. Loop
    until the document is actually empty rather than assuming one pass did it.
    """
    for _ in range(50):
        if not doc.Objects:
            return
        for obj in list(doc.Objects):
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
    raise CutterError("scratch document would not empty: %s"
                      % [o.Name for o in doc.Objects])


def _scratch_document():
    """An empty hidden document to sweep in, CREATED ONCE AND REUSED.

    DO NOT go back to creating and closing this per build.  Creating a
    document AND closing it inside a feature's execute() destroys the undo
    transaction the caller has open on a DIFFERENT document: the Part::Cut
    created after that recompute survives Ctrl-Z as a broken object whose
    Tool is gone, and the base part is left hidden, so the user sees nothing
    at all and cannot undo their way out of it.

    Isolated by bisection (tools/probe_undo_cause.py), because the cause was
    guessed wrong once already -- api.create_thread's docstring blamed the
    dependency DIAMOND (the cutter links to the base while the Cut consumes
    both), and that is measurably innocent: adding the identical diamond to a
    minimal fixture undoes cleanly, and removing AttachedTo from the real
    path leaves the bug exactly where it was.

    What the measurements actually say:

        create a document inside execute(), never close it   -> clean
        close a document inside execute() that predates it   -> clean
        create AND close inside execute()                    -> BROKEN
        the same create+close done by the CALLER instead     -> clean
        one long-lived document, reused, never closed        -> clean

    So it is specifically the pair, during a recompute. `temp=True` alone does
    not help -- measured, it still breaks.

    The document is `temp` so FreeCAD never offers to save it, hidden so it
    never appears in the tree, and UndoMode=0 so its own edits cost nothing.
    """
    if _SCRATCH_DOC:
        doc = _SCRATCH_DOC[0]
        try:
            if doc.Name in App.listDocuments():
                _empty(doc)
                return doc
        except Exception:
            pass                      # closed underneath us; make a new one
        del _SCRATCH_DOC[:]
    try:
        doc = App.newDocument(SCRATCH, hidden=True, temp=True)
    except TypeError:                 # older FreeCAD without `temp`
        doc = App.newDocument(SCRATCH, hidden=True)
    try:
        doc.UndoMode = 0
    except Exception:
        pass
    _SCRATCH_DOC.append(doc)
    return doc


def build(points, pitch, height, left_handed=False):
    """Sweep `points` (radius, axial) into a helical solid.

    Returns a Part.Shape detached from any document.
    """
    if len(points) < 3:
        raise CutterError("a cutter profile needs at least 3 corners")
    if pitch <= 0.0 or height <= 0.0:
        raise CutterError("pitch and height must both be positive")

    # RESTORE THE ACTIVE DOCUMENT AFTERWARDS.
    #
    # App.newDocument() makes the new document active even with hidden=True,
    # and App.closeDocument() does not hand that status back -- it leaves
    # App.ActiveDocument as None. Every FreeCAD GUI command works on the
    # active document, so after one thread the whole application appeared
    # broken: adding a part raised "'NoneType' object has no attribute
    # 'addObject'", and nothing could be deleted either. It is also what made
    # the task panel's Cancel raise on App.ActiveDocument.abortTransaction --
    # a symptom I patched at the call site before finding this cause.
    #
    # Still needed with a reused document: the FIRST call creates it, and
    # creation alone is enough to steal active status.
    previous = App.ActiveDocument
    doc = _scratch_document()
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
        # Empty it rather than close it -- closing is half of what breaks the
        # caller's undo (see _scratch_document). Leaving it empty between
        # builds also means no Body sits in memory holding a helix.
        try:
            _empty(doc)
        except Exception:
            pass          # the next acquire empties it; never mask a raise
        # Guarded: `previous` may legitimately be None (nothing was active),
        # and a caller could in principle have closed it while we worked.
        if previous is not None:
            try:
                App.setActiveDocument(previous.Name)
            except Exception:
                pass


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


def crest_relief(mode, surface_radius, crest_radius, z_lo, z_hi, overrun):
    """A cylindrical shell that takes the surface down (or out) to the crest.

    Clearance is applied RADIALLY: relieve the blank, then anchor the thread
    profile on the relieved surface.  That is what keeps the lands at their
    requested widths instead of paying for clearance out of the crest land
    (see form.crest_radius).

    Physically this is what a real die does -- it reduces the OD a little as
    it cuts -- and what printed_threads builds directly into its shank
    radius.  Here the blank already exists, so the reduction has to be part
    of the cutting tool.

    Built by revolving a closed RECTANGLE, not by subtracting one cylinder
    from another: two coaxial cylinders are the mildest boolean there is, but
    a revolve is no boolean at all, and this project's own history is a list
    of booleans that returned valid-looking garbage.

    Returns None when there is nothing to relieve, so a zero clearance costs
    nothing and adds no solid to the compound.

    `mode` decides which way the shell spans.  It used to be INFERRED from
    `crest_radius < surface_radius`, which is true for every input reachable
    today -- but that means the function cannot tell "external with a
    negative clearance" from "internal", and would then relieve a shaft
    OUTWARDS, taking material from below its own surface.  The caller knows
    the mode; re-deriving it from a subtraction bought nothing.
    """
    if mode not in (form.INTERNAL, form.EXTERNAL):
        raise CutterError(
            "mode %r is not %s or %s" % (mode, form.INTERNAL, form.EXTERNAL))
    if z_hi <= z_lo:
        raise CutterError(
            "crest relief range [%.4f, %.4f] is empty or inverted"
            % (z_lo, z_hi))
    if abs(crest_radius - surface_radius) < 1e-9:
        return None
    if crest_radius <= 0.0:
        raise CutterError(
            "crest relief would take the surface to r=%.4f, at or through "
            "the axis" % crest_radius)

    # Span from the relieved surface out past the original one, so the shell
    # certainly reaches material at every azimuth.
    if mode == form.EXTERNAL:                    # shave the shaft
        r_lo = min(crest_radius, surface_radius)
        r_hi = surface_radius + overrun
    else:                                        # open the bore
        r_lo = max(min(surface_radius, crest_radius) - overrun, 1e-6)
        r_hi = max(crest_radius, surface_radius)

    pts = [App.Vector(r_lo, 0.0, z_lo), App.Vector(r_hi, 0.0, z_lo),
           App.Vector(r_hi, 0.0, z_hi), App.Vector(r_lo, 0.0, z_hi)]
    face = Part.Face(Part.makePolygon(pts + [pts[0]]))
    solid = face.revolve(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 360.0)
    if not solid.isValid() or not solid.Solids:
        raise CutterError("crest relief revolve produced an invalid solid")
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
