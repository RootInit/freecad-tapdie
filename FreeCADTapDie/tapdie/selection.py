"""Turn a user selection into an axis, a radius and a thread mode."""

import collections
import math

import FreeCAD as App
import Part

from . import form

Circle = collections.namedtuple(
    "Circle", ["centre", "axis", "radius", "mode", "length", "direction"])

# Probe offsets, tried largest first, so a thin wall still gets an answer.
PROBE_FRACTIONS = (0.05, 0.01, 0.002)
MIN_PROBE = 1e-4


class SelectionError(Exception):
    """The selection is not something that can be threaded."""


class AmbiguousMode(SelectionError):
    """Internal vs external could not be determined; ask the user."""


def _circular_edges(face):
    """Distinct circles bounding `face`, largest first.

    Deduplicated on centre and radius: a face split by a seam can present the
    same circle as two edges, and reporting that as an ambiguity would send
    the user away for no reason.
    """
    seen, circles = set(), []
    for edge in face.Edges:
        curve = edge.Curve
        if not isinstance(curve, Part.Circle):
            continue
        key = (round(curve.Center.x, 6), round(curve.Center.y, 6),
               round(curve.Center.z, 6), round(curve.Radius, 6))
        if key in seen:
            continue
        seen.add(key)
        circles.append(edge)
    circles.sort(key=lambda e: e.Curve.Radius, reverse=True)
    return circles


def _from_planar_face(face, solid):
    """A FLAT circular face -- the end of a rod, the top of a boss.

    Threading is defined by a circle, and the disc at the end of a rod names
    one just as well as the rod's own side does. It is also a far easier
    thing to click: an end face is a big target, where the edge around it is
    a one-pixel line.

    An annulus (the end of a tube) bounds TWO circles and there is no way to
    tell which one is meant, so that case asks rather than guessing -- the
    edge is one click away and says so unambiguously.
    """
    circles = _circular_edges(face)
    if not circles:
        raise SelectionError(
            "that flat face has no circular edge to thread; select a "
            "cylindrical face or a circular edge")
    if len(circles) > 1:
        raise SelectionError(
            "that face has %d circular edges (%s mm across) and either could "
            "be meant; select the circular edge you want instead"
            % (len(circles),
               ", ".join("%.2f" % (2.0 * e.Curve.Radius) for e in circles)))
    return _from_edge(circles[0], solid)


def _from_face(face, solid):
    surface = face.Surface
    if isinstance(surface, Part.Plane):
        return _from_planar_face(face, solid)
    if not isinstance(surface, Part.Cylinder):
        raise SelectionError(
            "select a cylindrical face, a flat circular face, or a circular "
            "edge")
    axis = App.Vector(surface.Axis)
    axis.normalize()

    # A Part.Cylinder is parametrised (u = angle, v = axial distance), so the
    # TRIMMED face's v-range is exactly its axial length.  Do not replace this
    # with a bounding-box formula: summing bb extents times axis components is
    # only correct when the axis is axis-aligned, and is 34.6% wrong on a
    # cylinder tilted 30 degrees off X/Y/Z.
    u0, u1, v0, v1 = face.ParameterRange
    length = abs(v1 - v0)

    # THE FACE MUST GO ALL THE WAY ROUND. A FILLET is a cylindrical face too,
    # and so is the wall of a slot -- neither has material at every azimuth,
    # so threading one cuts a helix around an axis that is mostly empty air.
    # Measured before this guard: a half cylinder resolved happily, reporting
    # r=4.00 and a 20mm run, and would have been threaded without a word.
    sweep = abs(u1 - u0)
    if sweep < 2.0 * math.pi - 1e-4:
        raise SelectionError(
            "that cylindrical face only goes %.0f degrees round, so it is a "
            "fillet or the wall of a slot rather than a shaft or a bore; "
            "select a full cylinder or the circular edge you want"
            % math.degrees(sweep))

    # surface.Center is the origin of the UNTRIMMED surface's local frame, not
    # a point on the trimmed face -- on a counterbore built from coaxial
    # cylinders sharing an origin, that can be well outside this face's real
    # z-range.  Project the face's centroid onto the axis instead, anchored
    # at surface.Center so a face split by a seam (whose raw CenterOfMass is
    # off-axis) still lands back on the axis.
    base = App.Vector(surface.Center)
    com = face.CenterOfMass
    centre = base + axis * (com - base).dot(axis)

    return centre, axis, surface.Radius, length


def _from_edge(edge, solid):
    curve = edge.Curve
    if not isinstance(curve, Part.Circle):
        raise SelectionError("select a cylindrical face or a circular edge")
    axis = App.Vector(curve.Axis)
    axis.normalize()

    # max(bb extents) conflates axial length with radial bulge -- wrong for
    # any solid that isn't axis-aligned, and arbitrarily wrong for a short fat
    # one.  Project every vertex onto the axis and take the span instead.
    proj = [App.Vector(v.Point).dot(axis) for v in solid.Vertexes]
    length = (max(proj) - min(proj)) if proj else 0.0

    # curve.Center is the true circle centre regardless of trimming -- an
    # edge's defining circle has no separate "untrimmed surface frame" the
    # way a face's underlying cylinder does, so this path does not share the
    # face-centre bug above.
    return App.Vector(curve.Center), axis, curve.Radius, length


def _element(shape, sub_name):
    """getElement() raises several unrelated exception types (IndexError,
    Part.OCCError, ...) for a stale or out-of-range subelement name -- a
    realistic case when a selection survives a topology-changing recompute.
    Funnel them all into SelectionError so callers only need one except."""
    try:
        return shape.getElement(sub_name)
    except Exception:
        raise SelectionError(
            "%s is not a subelement of this shape; the selection may be "
            "stale" % sub_name)


def detect_mode(solid, centre, axis, radius):
    """Decide internal vs external by probing just inside and just outside.

    checkFace=True is required: with the default, a circle lying on a flat end
    face reads False/False and gives no signal at all.
    """
    ref = App.Vector(1, 0, 0)
    if abs(ref.dot(axis)) > 0.9:
        ref = App.Vector(0, 1, 0)
    radial = ref.cross(axis)
    radial.normalize()

    for fraction in PROBE_FRACTIONS:
        eps = max(radius * fraction, MIN_PROBE)
        inner = centre + radial * (radius - eps)
        outer = centre + radial * (radius + eps)
        in_solid = solid.isInside(inner, 1e-7, True)
        out_solid = solid.isInside(outer, 1e-7, True)
        if in_solid and not out_solid:
            return form.EXTERNAL
        if out_solid and not in_solid:
            return form.INTERNAL
        if in_solid and out_solid:
            # Both solid: a counterbore step, or the probe landed in bulk
            # material unrelated to this circle.  A smaller probe will not
            # help, so stop.
            raise AmbiguousMode(
                "material on both sides of the selected circle; set Mode by "
                "hand (counterbore or stepped feature?)")
    raise AmbiguousMode(
        "no material on either side of the selected circle; set Mode by hand")


def _radial_unit(axis):
    ref = App.Vector(1, 0, 0)
    if abs(ref.dot(axis)) > 0.9:
        ref = App.Vector(0, 1, 0)
    radial = ref.cross(axis)
    radial.normalize()
    return radial


def detect_direction(solid, centre, axis, radius, mode):
    """Which way along the axis the material lies from this circle.

    Only meaningful for an EDGE selection, where the circle sits at one end
    of the feature and cutting both ways would put half the cutter in open
    air.  A cylindrical FACE already spans its own run, so resolve() reports
    BOTH for one without probing.

    Probes just inside the wall -- radius - eps for a shaft, radius + eps for
    a bore -- one step each way along the axis.  Returns None when both sides
    or neither has material, so the caller can fall back rather than guess.
    """
    radial = _radial_unit(axis)
    for fraction in PROBE_FRACTIONS:
        eps = max(radius * fraction, MIN_PROBE)
        wall = radius - eps if mode == form.EXTERNAL else radius + eps
        base = centre + radial * wall
        # checkFace=True for the same reason detect_mode needs it: a probe
        # that lands on a flat end face otherwise reads False on both sides
        # and gives no signal at all.
        ahead = solid.isInside(base + axis * eps, 1e-7, True)
        behind = solid.isInside(base - axis * eps, 1e-7, True)
        if ahead and not behind:
            return form.FORWARD
        if behind and not ahead:
            return form.REVERSE
        if ahead and behind:
            return None      # mid-feature: a smaller probe will not help
    return None


def resolve(obj, sub_name):
    """Resolve (object, subelement name) to a Circle.

    `mode` is None when detection was ambiguous, so callers can fall back to
    asking rather than guessing.
    """
    shape = obj.Shape
    if sub_name.startswith("Face"):
        face = _element(shape, sub_name)
        centre, axis, radius, length = _from_face(face, shape)
        # A cylindrical face IS the run: its own midpoint is the anchor and
        # its own length the extent, so straddling is exactly right and no
        # probe is needed. A FLAT circular face is not -- it sits at one end
        # of the feature exactly as an edge does, and is handled as one.
        from_edge = isinstance(face.Surface, Part.Plane)
    elif sub_name.startswith("Edge"):
        edge = _element(shape, sub_name)
        centre, axis, radius, length = _from_edge(edge, shape)
        from_edge = True
    else:
        raise SelectionError(
            "select a cylindrical face, a flat circular face, or a circular "
            "edge, not %s" % sub_name)

    if radius <= 0.0:
        raise SelectionError("selected circle has no radius")

    try:
        mode = detect_mode(shape, centre, axis, radius)
    except AmbiguousMode:
        mode = None

    direction = form.BOTH
    if from_edge:
        # An edge sits at ONE end of the feature, and _from_edge reports the
        # whole solid's axial span as the length -- so straddling would put
        # half a full-length run in open air and thread only half the part.
        # Fall back to BOTH only when the probe cannot tell.
        detected = None
        if mode is not None:
            detected = detect_direction(shape, centre, axis, radius, mode)
        direction = detected or form.BOTH

    return Circle(centre=centre, axis=axis, radius=radius, mode=mode,
                  length=length, direction=direction)
