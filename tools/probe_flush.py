"""Does FlushEnds change the CUT, or only the cutter?

The overrun exists so the groove runs past the end face rather than leaving a
collar of plain surface for the mating crest to jam on (CLAUDE.md). Facing the
cutter off flat at the run's ends removes that overrun -- so the question that
decides whether FlushEnds is cosmetic or structural is whether the boolean
result differs.

Measured on a plain shaft (both ends free, the case where the overrun has the
most room to matter) and on a hex-head rod (one end abutting).
"""

import os
import sys

import FreeCAD as App
import Part

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "FreeCADTapDie"))

from tapdie import api, form  # noqa: E402


def cyl_face(obj, radius):
    for i, face in enumerate(obj.Shape.Faces):
        surface = face.Surface
        if hasattr(surface, "Radius") and abs(surface.Radius - radius) < 1e-6:
            return "Face%d" % (i + 1)
    raise SystemExit("no face at r=%.3f" % radius)


def run(label, make_base, radius, overrides):
    results = {}
    for flush in (False, True):
        doc = App.newDocument("flush")
        try:
            base = make_base(doc)
            doc.recompute()
            params = dict(overrides)
            params["FlushEnds"] = flush
            cutter_obj, cut = api.create_thread(
                doc, base, cyl_face(base, radius), params)
            doc.recompute()
            results[flush] = (cut.Shape.Volume, len(cut.Shape.Solids),
                              cut.Shape.isValid())
        finally:
            App.closeDocument(doc.Name)

    (v_off, n_off, ok_off) = results[False]
    (v_on, n_on, ok_on) = results[True]
    print("%-26s overrun %10.4f mm3 (%d solids, valid=%s)"
          % (label, v_off, n_off, ok_off))
    print("%-26s flush   %10.4f mm3 (%d solids, valid=%s)"
          % ("", v_on, n_on, ok_on))
    print("%-26s difference %.6f mm3  -> %s"
          % ("", v_on - v_off,
             "IDENTICAL cut" if abs(v_on - v_off) < 1e-6
             else "DIFFERENT cut"))
    print()


def plain_shaft(doc):
    obj = doc.addObject("Part::Cylinder", "Shaft")
    obj.Radius, obj.Height = 4.0, 30.0
    return obj


def hex_head_rod(doc):
    head = doc.addObject("Part::Box", "Head")
    head.Length = head.Width = 7.0
    head.Height = 8.0
    head.Placement.Base = App.Vector(-3.5, -3.5, 0)
    shaft = doc.addObject("Part::Cylinder", "Shaft")
    shaft.Radius, shaft.Height = 2.0, 22.0
    shaft.Placement.Base = App.Vector(0, 0, 8.0)
    rod = doc.addObject("Part::Fuse", "Rod")
    rod.Base, rod.Tool = head, shaft
    return rod


run("plain shaft M8x1.25", plain_shaft, 4.0,
    {"Mode": form.EXTERNAL, "Diameter": 8.0, "Pitch": 1.25, "Length": 20.0})

run("hex head rod M4x0.7", hex_head_rod, 2.0,
    {"Mode": form.EXTERNAL, "Diameter": 4.0, "Pitch": 0.7, "Length": 20.0})
