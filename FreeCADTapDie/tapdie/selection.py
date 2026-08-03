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
    bb = face.optimalBoundingBox()
    axis = App.Vector(surface.Axis)
    axis.normalize()
    length = abs(bb.ZLength * axis.z) + abs(bb.YLength * axis.y) \
        + abs(bb.XLength * axis.x)
    return App.Vector(surface.Center), axis, surface.Radius, length


def _from_edge(edge, solid):
    curve = edge.Curve
    if not isinstance(curve, Part.Circle):
        raise SelectionError("select a cylindrical face or a circular edge")
    axis = App.Vector(curve.Axis)
    axis.normalize()
    bb = solid.optimalBoundingBox()
    length = max(bb.XLength, bb.YLength, bb.ZLength)
    return App.Vector(curve.Center), axis, curve.Radius, length


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
        face = shape.getElement(sub_name)
        centre, axis, radius, length = _from_face(face)
    elif sub_name.startswith("Edge"):
        edge = shape.getElement(sub_name)
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
