"""Does FlushEnds damage the lead-in chamfer?

test_internal_chamfer_reaches_full_relief_radius started failing when
FlushEnds defaulted on. Either the clip is eating the chamfer -- a real
defect, since clip_to_axial_range uses Shape.common() and CLAUDE.md warns
that common() on helical faces is unreliable -- or the test's probe point
is simply no longer where it assumes. Measure rather than reason.
"""

import math
import os
import sys

import FreeCAD as App

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "FreeCADTapDie"))

from tapdie import feature, form  # noqa: E402

doc = App.newDocument("chamfer")


def full_circle_removed(shape, radius, z, steps=24):
    for deg in range(0, 360, 360 // steps):
        rad = math.radians(deg)
        p = App.Vector(radius * math.cos(rad), radius * math.sin(rad), z)
        if not shape.isInside(p, 1e-7, True):
            return False
    return True


for flush in (False, True):
    obj = feature.make_cutter(doc)
    obj.Mode = form.INTERNAL
    obj.ThreadForm = form.ISO
    obj.Pitch = 1.25
    obj.Diameter = 8.0
    obj.SurfaceRadius = 3.3234
    obj.Length = 8.0
    obj.FlushEnds = flush
    doc.recompute()

    points = form.cutter_points(
        obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
        obj.Angle.Value, obj.RootLand.Value, obj.CrestLand.Value,
        obj.Clearance.Value, obj.SurfaceRadius.Value, obj.Overrun.Value)
    tip = points[0][0]
    half = obj.Length.Value / 2.0
    box = obj.Shape.optimalBoundingBox()

    print("FlushEnds=%-5s  solids=%d  z %.4f .. %.4f  (run is %.4f .. %.4f)"
          % (flush, len(obj.Shape.Solids), box.ZMin, box.ZMax, -half, half))
    print("   tip radius %.4f   NearEndFree=%s FarEndFree=%s"
          % (tip, obj.NearEndFree, obj.FarEndFree))
    for label, z in (("near face + 0.01", -half + 0.01),
                     ("far face  - 0.01", half - 0.01)):
        print("      %s at r=%.4f : all azimuths removed = %s"
              % (label, tip - 0.02,
                 full_circle_removed(obj.Shape, tip - 0.02, z)))
    # Which solid covers the probe? Isolate them, so "the clip ate the
    # chamfer" can be told apart from "isInside on a compound is unreliable".
    for i, solid in enumerate(obj.Shape.Solids):
        sb = solid.optimalBoundingBox()
        covered = full_circle_removed(solid, tip - 0.02, -half + 0.01)
        print("      solid %d: z %8.4f..%8.4f r<=%7.4f  covers near probe=%s"
              % (i, sb.ZMin, sb.ZMax, sb.XMax, covered))
    print("      cutter starts %.4f before the run's low end"
          % (-half - box.ZMin))
    print()
    doc.removeObject(obj.Name)

App.closeDocument(doc.Name)
