"""Section a threaded solid on the axial plane and dump the REAL profile.

Reads segment lengths, radii and angles straight off the cut solid rather
than off the arithmetic that built it -- the printed_threads probe_profile.py
pattern, for the same reason: the profile maths and the solid disagree, and
only the solid matters.

Reports, per mode:
  * every section segment in a mid-length window, with its angle
  * the cylindrical bands (true lands) and their widths
  * the axial period, which must equal Pitch
  * the RADIAL SWEEP of the cut: the deepest and shallowest radius the groove
    reaches.  Material left between turns shows up here as a groove that
    never reaches the intended root radius.

Usage: ... probe_thread.py [External|Internal]
"""

import math
import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "FreeCADTapDie"))

from tapdie import api, form, presets  # noqa: E402

MODE = sys.argv[-1] if sys.argv[-1] in ("External", "Internal") else "External"

DIAMETER = 8.0
PITCH = 1.25
LENGTH = 20.0
SHAFT_LEN = 30.0


def build():
    doc = App.newDocument("probe")
    if MODE == form.EXTERNAL:
        base = doc.addObject("Part::Cylinder", "Shaft")
        base.Radius = DIAMETER / 2.0
        base.Height = SHAFT_LEN
        surface_radius = DIAMETER / 2.0
    else:
        outer = doc.addObject("Part::Cylinder", "Outer")
        outer.Radius = DIAMETER
        outer.Height = SHAFT_LEN
        bore = doc.addObject("Part::Cylinder", "Bore")
        # ISO tap drill for M8x1.25.
        bore.Radius = 6.75 / 2.0
        bore.Height = SHAFT_LEN + 2.0
        bore.Placement.Base = App.Vector(0, 0, -1)
        base = doc.addObject("Part::Cut", "Blank")
        base.Base, base.Tool = outer, bore
        surface_radius = 6.75 / 2.0
    doc.recompute()

    # Find the face on the cylindrical surface being threaded.
    target = None
    for i, face in enumerate(base.Shape.Faces):
        if not hasattr(face.Surface, "Radius"):
            continue
        if abs(face.Surface.Radius - surface_radius) < 1e-6:
            target = "Face%d" % (i + 1)
            break
    if target is None:
        raise SystemExit("no cylindrical face at r=%.4f" % surface_radius)

    cutter_obj, cut = api.create_thread(doc, base, target, {
        "Mode": MODE, "ThreadForm": form.PRINTED,
        "Diameter": DIAMETER, "Pitch": PITCH, "Length": LENGTH,
    })
    doc.recompute()
    return doc, cutter_obj, cut, surface_radius


doc, cutter_obj, cut, surface_radius = build()

lands = presets.form_defaults(form.PRINTED, PITCH)
points = form.cutter_points(
    MODE, form.PRINTED, DIAMETER, PITCH, lands["angle"], lands["root_land"],
    lands["crest_land"], cutter_obj.Clearance.Value, surface_radius,
    cutter_obj.Overrun.Value)

print("mode %s   pitch %.4f   angle %.1f" % (MODE, PITCH, lands["angle"]))
print("lands from preset: root %.4f  crest %.4f"
      % (lands["root_land"], lands["crest_land"]))
crest_r = form.crest_radius(MODE, surface_radius, cutter_obj.Clearance.Value,
                            lands["angle"])
print("surface radius %.4f   crest radius after relief %.4f (offset %.4f)"
      % (surface_radius, crest_r,
         form.radial_offset(cutter_obj.Clearance.Value, lands["angle"])))
print("cutter profile (radius, axial):")
for r, v in points:
    print("      r %9.4f   v %+9.4f" % (r, v))
tip_r = points[0][0]
print("   -> tip (thread root) r %.4f, so intended radial depth %.4f"
      % (tip_r, abs(surface_radius - tip_r)))
print()

shape = cut.Shape.copy()
shape.Placement = App.Placement()

# Shape.slice() returns zero wires on solids like these at the plane through
# the axis -- no error, just an empty result. Section against an explicit face.
span = DIAMETER * 3
pts = [App.Vector(-span, 0, -10), App.Vector(span, 0, -10),
       App.Vector(span, 0, SHAFT_LEN + 10), App.Vector(-span, 0, SHAFT_LEN + 10)]
plane = Part.Face(Part.makePolygon(pts + [pts[0]]))

# Mid-length window, well clear of both lead-in chamfers.
z_mid = SHAFT_LEN / 2.0
z_lo, z_hi = z_mid - 2.0 * PITCH, z_mid + 2.0 * PITCH
r_lo = min(tip_r, crest_r) - 0.6
r_hi = max(tip_r, crest_r) + 0.6

segs = []
for e in shape.section(plane).Edges:
    a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
    if min(a.x, b.x) < 0.5:
        continue
    if not (r_lo <= a.x <= r_hi and r_lo <= b.x <= r_hi):
        continue
    if not (z_lo < a.z < z_hi and z_lo < b.z < z_hi):
        continue
    segs.append((a, b))

segs.sort(key=lambda s: min(s[0].z, s[1].z))

print("section segments, x>0 side, r in [%.3f, %.3f], z in [%.2f, %.2f]"
      % (r_lo, r_hi, z_lo, z_hi))
print("%9s %9s %9s %9s %9s  %s"
      % ("len", "r0", "z0", "r1", "z1", "what"))
for a, b in segs:
    dr, dz = b.x - a.x, b.z - a.z
    length = math.hypot(dr, dz)
    if abs(dr) < 1e-6:
        what = "AXIAL  (cylindrical band -- a land)"
    elif abs(dz) < 1e-6:
        what = "RADIAL (flat face, normal along z)"
    else:
        # Half the included angle, measured off the axis: a 90 deg thread
        # has 45 deg flanks by this convention.
        what = "flank, %.2f deg off axis" % math.degrees(
            math.atan2(abs(dr), abs(dz)))
    print("%9.4f %9.4f %9.4f %9.4f %9.4f  %s"
          % (length, a.x, a.z, b.x, b.z, what))

bands = [(a, b) for a, b in segs if abs(b.x - a.x) < 1e-6]
print()
print("cylindrical bands (true lands), %d found:" % len(bands))
for a, b in bands:
    w = abs(b.z - a.z)
    which = ("crest" if abs(a.x - crest_r) < 0.005 else
             "root" if abs(a.x - tip_r) < 0.005 else "UNEXPECTED")
    print("   r %9.4f   width %8.4f mm  (%5.1f%% of pitch)   %s"
          % (a.x, w, 100.0 * w / PITCH, which))

# Ray probes along the axis at the two radii that matter. Keep each ray
# shorter than the pitch (CLAUDE.md: a longer ray sums two features and
# reports one wide one).
print()
print("axial ray probes (ray length %.3f < pitch %.3f)" % (PITCH * 0.9, PITCH))
for label, r in (("just inside the crest", crest_r +
                  (-0.02 if MODE == form.EXTERNAL else 0.02)),
                 ("at the intended root  ", tip_r +
                  (0.02 if MODE == form.EXTERNAL else -0.02))):
    z0 = z_mid - PITCH * 0.45
    ray = Part.makeLine(App.Vector(r, 0, z0),
                        App.Vector(r, 0, z0 + PITCH * 0.9))
    solid_len = sum(e.Length for e in ray.common(shape).Edges)
    void_len = sum(e.Length for e in ray.cut(shape).Edges)
    print("   r %8.4f  %s  material %7.4f   void %7.4f"
          % (r, label, solid_len, void_len))

App.closeDocument(doc.Name)
