"""Does the lead-in chamfer stay inside the threaded run?

Answer, on 2026-08-04: NO, not when the run is shorter than the chamfer's own
reach. A lead-in cone is 45 degrees, so its AXIAL reach equals its RADIAL
depth, cut_depth + radial_offset. feature.py fused the cones in AFTER
clip_to_axial_range, so nothing bounded them, while a comment asserted the
opposite ("the chamfer sits entirely within [feature_lo, feature_hi]").

Measured on a 4mm stub against an 8mm shoulder, run [0, 1], pitch 3.8:

    NearEndFree = False   FarEndFree = True
    chamfer axial reach 1.6697 vs Length 1.0000 -> overreach 0.6697
    cutter z-extent [-0.6959, 1.0442]
    shoulder ray at z=-0.3   before 7.5000   after 7.1303
    MAX MATERIAL LOST FROM THE SHOULDER: 0.3697 mm

That is the same defect class the free/abutting end detection was built to
prevent (48.5915 mm3 out of a hex head), reintroduced by the feature added
after it. Fixed by clipping the cones to the same range as the sweep.

Material is measured with RAY PROBES, not booleans: CLAUDE.md records
common() returning negative volumes and solid-less results on near-tangent
helical faces, and isInside() reading False for a point inside a compound.

    flatpak run --command=freecadcmd org.freecad.FreeCAD \\
        tools/probe_chamfer_overreach.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "FreeCADTapDie"))

import FreeCAD as App                                        # noqa: E402
import Part                                                  # noqa: E402

from tapdie import feature, form                             # noqa: E402


def radial_material(shape, z, r_max=7.5, azimuths=12):
    """Material a radial ray crosses at height `z`, per azimuth."""
    out = []
    for i in range(azimuths):
        t = 2.0 * math.pi * i / azimuths
        ray = Part.makeLine(App.Vector(0, 0, z),
                            App.Vector(r_max * math.cos(t),
                                       r_max * math.sin(t), z))
        out.append(sum(e.Length for e in ray.common(shape).Edges))
    return out


doc = App.newDocument("chamferprobe")

# The shaft occupies z in [0, 1] ONLY, so its top really is free. An earlier
# version of this probe ran the shaft to z=20 and both ends read ABUTTING --
# no chamfer was built at all and the probe reported "clean" for the wrong
# reason. A fixture that cannot exhibit the defect proves nothing.
stub = Part.makeCylinder(4.0, 1.0, App.Vector(0, 0, 0))
shoulder = Part.makeCylinder(8.0, 5.0, App.Vector(0, 0, -5.0))
base = doc.addObject("Part::Feature", "Blank")
base.Shape = stub.fuse(shoulder).removeSplitter()
doc.recompute()

obj = feature.make_cutter(doc)
obj.Mode = form.EXTERNAL
obj.ThreadForm = form.PRINTED
obj.Pitch = 3.8
obj.Diameter = 8.0
obj.SurfaceRadius = 4.0
obj.Length = 1.0
obj.Direction = form.FORWARD
obj.Clearance = 0.12
obj.LeadIn = True
obj.FlushEnds = True
obj.AttachedTo = base
obj.LocalPlacement = App.Placement()
doc.recompute()

print("cutter State = %s" % obj.State)
print("NearEndFree (z=0, at the shoulder) = %s   (want False)"
      % obj.NearEndFree)
print("FarEndFree  (z=+1, open air)       = %s   (want True)"
      % obj.FarEndFree)

points = form.cutter_points(
    obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
    obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
    obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
reach = abs(points[0][0] - obj.SurfaceRadius.Value)
print("chamfer axial reach %.4f vs Length %.4f -> overreach %.4f"
      % (reach, obj.Length.Value, reach - obj.Length.Value))

box = obj.Shape.optimalBoundingBox()
print("cutter z-extent [%.4f, %.4f]   (the run is [0, 1])"
      % (box.ZMin, box.ZMax))

before = radial_material(base.Shape, -0.3)
cut = doc.addObject("Part::Cut", "Thread")
cut.Base, cut.Tool = base, obj
doc.recompute()
after = radial_material(cut.Shape, -0.3)
lost = max(b - a for b, a in zip(before, after))

print("shoulder ray at z=-0.3 before: %s" % [round(v, 4) for v in before])
print("shoulder ray at z=-0.3 after : %s" % [round(v, 4) for v in after])
print("MAX MATERIAL LOST FROM THE SHOULDER: %.4f mm" % lost)

ok = lost <= 1e-4 and box.ZMin >= -1e-6
print("\nPROBE: %s" % ("clean" if ok else "GOUGED THE SHOULDER"))
App.closeDocument(doc.Name)
# os._exit skips interpreter shutdown, so it also skips flushing stdout --
# and everything above is then silently discarded (CLAUDE.md: "stdout is
# buffered"). Flush by hand or this probe reports nothing but its status.
sys.stdout.flush()
os._exit(0 if ok else 1)
