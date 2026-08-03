"""Turn a user selection into an axis, a radius and a thread mode."""

import collections

import FreeCAD as App
import Part

from . import form

Circle = collections.namedtuple(
    "Circle", ["centre", "axis", "radius", "mode", "length"])

# Probe offsets, tried largest first, so a thin wall still gets an answer.
PROBE_FRACTIONS = (0.05, 0.01, 0.002)
MIN_PROBE = 1e-4


class SelectionError(Exception):
    """The selection is not something that can be threaded."""


class AmbiguousMode(SelectionError):
    """Internal vs external could not be determined; ask the user."""


def _from_face(face):
    surface = face.Surface
    if not isinstance(surface, Part.Cylinder):
        raise SelectionError("select a cylindrical face or a circular edge")
    axis = App.Vector(surface.Axis)
    axis.normalize()

    # A Part.Cylinder is parametrised (u = angle, v = axial distance), so the
    # TRIMMED face's v-range is exactly its axial length.  Do not replace this
    # with a bounding-box formula: summing bb extents times axis components is
    # only correct when the axis is axis-aligned, and is 34.6% wrong on a
    # cylinder tilted 30 degrees off X/Y/Z.
    _u0, _u1, v0, v1 = face.ParameterRange
    length = abs(v1 - v0)

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


def resolve(obj, sub_name):
    """Resolve (object, subelement name) to a Circle.

    `mode` is None when detection was ambiguous, so callers can fall back to
    asking rather than guessing.
    """
    shape = obj.Shape
    if sub_name.startswith("Face"):
        face = _element(shape, sub_name)
        centre, axis, radius, length = _from_face(face)
    elif sub_name.startswith("Edge"):
        edge = _element(shape, sub_name)
        centre, axis, radius, length = _from_edge(edge, shape)
    else:
        raise SelectionError(
            "select a cylindrical face or a circular edge, not %s" % sub_name)

    if radius <= 0.0:
        raise SelectionError("selected circle has no radius")

    try:
        mode = detect_mode(shape, centre, axis, radius)
    except AmbiguousMode:
        mode = None

    return Circle(centre=centre, axis=axis, radius=radius, mode=mode,
                  length=length)
