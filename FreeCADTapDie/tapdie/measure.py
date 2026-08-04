"""Measure a built solid's thread profile off a plane section.

A valid solid is not a correct solid.  Every MakePipeShell variant tested
during design returned isValid() == True with exactly one solid while carrying
the wrong flank angle, so validity is a precondition and this module is the
actual guard.
"""

import math

import FreeCAD as App
import Part

AXIAL_TOL = 1e-6
MIN_RADIUS = 1.0


def cut_plane(reach=200.0):
    """A real face on y=0, big enough to pass through any plausible part.

    Shape.slice(Vector(0,1,0), 0) returns ZERO wires on solids of revolution
    here -- no error, just an empty result that reads as 'the plane missed the
    solid'.  Sectioning against an explicit face cannot fail that way.
    """
    pts = [App.Vector(-reach, 0, -reach), App.Vector(reach, 0, -reach),
           App.Vector(reach, 0, reach), App.Vector(-reach, 0, reach)]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def profile(shape, z_lo, z_hi, r_max=None):
    """Straight segments of the profile on the +x side of y=0.

    `flank_angles` are ISO flank angles: the angle between a flank and the
    plane perpendicular to the axis, i.e. HALF the included angle.  At a
    90 degree included angle this happens to equal the angle measured from
    the axis, which is why the two conventions are easy to confuse -- they
    only differ once you test a form that is not 90 degrees.

    Also returns cylindrical bands (lands) as (radius, axial width), and
    SHELVES as (axial position, radial width).  Only segments lying wholly
    inside the z window are considered, so partial features at the window
    edges cannot skew it.

    A shelf is a flat annulus normal to the axis, standing between a crest
    and a flank.  It is what a cutter leaves when its flank stops short of
    the surface and the parallel section covers the difference -- the
    "material left between pitches" defect.  It gets its own key because
    this function used to have a BLIND SPOT exactly there: a segment counted
    as a land when dr was ~0 and as a flank when dz was not ~0, so a shelf
    (dz ~0, dr large) matched neither and was silently discarded.  Every
    profile assertion in the suite passed while 0.3697mm of shelf sat in the
    solid between every pair of turns.
    """
    flanks, lands, shelves, radii = [], [], [], []
    for edge in shape.section(cut_plane()).Edges:
        a = edge.Vertexes[0].Point
        b = edge.Vertexes[-1].Point
        if min(a.x, b.x) < MIN_RADIUS:
            continue
        if r_max is not None and max(a.x, b.x) > r_max:
            continue
        if not (z_lo < a.z < z_hi and z_lo < b.z < z_hi):
            continue
        radii.extend([a.x, b.x])
        dr, dz = b.x - a.x, b.z - a.z
        if abs(dr) < AXIAL_TOL:
            lands.append((round(a.x, 4), abs(dz)))
        elif abs(dz) < AXIAL_TOL:
            shelves.append((round(a.z, 4), abs(dr)))
        else:
            flanks.append(math.degrees(math.atan2(abs(dz), abs(dr))))

    return {
        "flank_angles": flanks,
        "lands": lands,
        "shelves": shelves,
        "r_min": min(radii) if radii else None,
        "r_max": max(radii) if radii else None,
    }
