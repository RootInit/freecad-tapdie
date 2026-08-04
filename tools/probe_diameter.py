"""Does `Diameter` change the cutter profile at all?

Answer, on 2026-08-04: NO. form.cutter_points took `diameter` and never
referenced it, so the most prominent field in the task panel changed nothing.
form.py's own comment called it "a check, not a driver" -- but the check was
never performed anywhere, and required_surface_radius(), which exists to
quantify exactly this, had no production caller at all.

    diameter= 8.0 -> [(3.430294, 0.1125), (3.830294, 0.5125), (5.0, 0.5125), ...]
    diameter=24.0 -> [(3.430294, 0.1125), (3.830294, 0.5125), (5.0, 0.5125), ...]
    IDENTICAL: True

Fixed by form.achieved_diameter() + api.diameter_note(), which report what the
selected blank will really produce. This probe stays as the negative control:
cutter_points SHOULD still ignore Diameter (the profile is anchored on the
surface, deliberately -- see form.py), so the first assertion below must keep
passing. What must not come back is the silence.

Pure Python; no FreeCAD needed.

    python3 tools/probe_diameter.py
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "FreeCADTapDie"))

from tapdie import form                                      # noqa: E402

KW = dict(pitch=1.25, angle=90.0, root_land=0.225, crest_land=0.225,
          clearance=0.12, surface_radius=4.0, overrun=1.0)

small = form.cutter_points(form.EXTERNAL, form.PRINTED, 8.0, **KW)
large = form.cutter_points(form.EXTERNAL, form.PRINTED, 24.0, **KW)

print("diameter= 8.0 -> %s" % [tuple(round(v, 6) for v in p) for p in small])
print("diameter=24.0 -> %s" % [tuple(round(v, 6) for v in p) for p in large])
print("profiles identical: %s   (expected True -- the surface anchors it)"
      % (small == large))

# The profile ignoring Diameter is by design. Going UNREPORTED was the bug.
achieved = form.achieved_diameter(form.EXTERNAL, KW["pitch"], KW["angle"],
                                  KW["root_land"], KW["crest_land"],
                                  KW["clearance"], KW["surface_radius"])
print("a %.1fmm blank asked for M8 really cuts %.4fmm"
      % (2 * KW["surface_radius"], achieved))
print("and required_surface_radius says M8 needs a %.4fmm blank"
      % (2 * form.required_surface_radius(
          form.EXTERNAL, 8.0, KW["pitch"], KW["angle"], KW["root_land"],
          KW["crest_land"], KW["clearance"])))

ok = small == large and abs(achieved - 8.0) < 1e-9
print("\nPROBE: %s" % ("ok" if ok else "UNEXPECTED"))
raise SystemExit(0 if ok else 1)
