"""How much room is there between a mated bolt and nut, in EVERY direction?

Reported 2026-08-04: "vertically there is good clearance but the flats have
very little clearance". Correct, and worse than "very little" -- it was zero.
Clearance is a radial shift of the whole profile, which opens exactly
2 * clearance normal to the FLANKS and nothing at all between a crest and the
root facing it, because required_surface_radius subtracted precisely
cut_depth + 2 * radial_offset and the two cancelled.

    today            flats gap  0.0000    minimum gap anywhere  0.0000
    nut bore +0.12   flats gap  0.1200    minimum gap anywhere  0.0849
    nut bore +0.24   flats gap  0.2400    minimum gap anywhere  0.1697

Fixed by sizing the internal BLANK larger by flat_clearance(), which lifts the
nut's crest and root together and leaves both profiles untouched.

This probe exists because two shapelier-looking fixes were reasoned out,
implemented, and both turned out wrong -- see form.flat_clearance for what
they were and how they failed. Deriving this by hand does not work; draw the
two boundaries and measure the distance.

    python3 tools/probe_mated_gap.py            # no FreeCAD needed
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "FreeCADTapDie"))

from tapdie import form, presets                             # noqa: E402


def boundary(crest, depth, pitch, root_land, crest_land, angle, turns=4):
    """One part's thread boundary as (z, r) points over several pitches.

    `depth` positive means the groove runs toward smaller r (a bolt);
    negative means toward larger r (a nut).
    """
    tan = math.tan(math.radians(angle / 2.0))
    sign = 1.0 if depth > 0 else -1.0
    d = abs(depth)
    pts = []
    for k in range(-turns, turns + 1):
        z0 = k * pitch
        pts.append((z0 - crest_land / 2.0, crest))
        pts.append((z0 + crest_land / 2.0, crest))
        pts.append((z0 + crest_land / 2.0 + d * tan, crest - sign * d))
        pts.append((z0 + pitch - crest_land / 2.0 - d * tan,
                    crest - sign * d))
    return sorted(set(pts))


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(
        0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def min_gap(a_pts, b_pts):
    """True minimum distance between two boundaries. No derivation."""
    best = float("inf")
    for p in a_pts:
        for i in range(len(b_pts) - 1):
            best = min(best, _seg_dist(p, b_pts[i], b_pts[i + 1]))
    for p in b_pts:
        for i in range(len(a_pts) - 1):
            best = min(best, _seg_dist(p, a_pts[i], a_pts[i + 1]))
    return best


ANGLE = 90.0
CLEARANCE = 0.12
RADIUS = 4.0

print("%-8s %-9s %-9s %-9s %-9s %s"
      % ("pitch", "land", "flankgap", "flatgap", "min-any", "verdict"))
worst = []
for pitch in (0.5, 0.7, 1.25, 2.5, 3.8):
    land = presets.form_defaults(form.PRINTED, pitch,
                                 form.EXTERNAL)["root_land"]
    depth = form.cut_depth(pitch, ANGLE, land, land)
    bolt_crest = form.crest_radius(form.EXTERNAL, RADIUS, CLEARANCE, ANGLE)
    bolt = boundary(bolt_crest, +depth, pitch, land, land, ANGLE)

    bore = form.required_surface_radius(form.INTERNAL, 2.0 * RADIUS, pitch,
                                        ANGLE, land, land, CLEARANCE)
    nut_crest = form.crest_radius(form.INTERNAL, bore, CLEARANCE, ANGLE)
    nut = boundary(nut_crest, -depth, pitch, land, land, ANGLE)
    # Half a pitch of phase, which is what form.start_phase applies as 180
    # degrees of rotation, or the pair simply collides.
    nut = [(z + pitch / 2.0, r) for z, r in nut]

    flat = (nut_crest + depth) - bolt_crest
    flank = 2.0 * CLEARANCE
    anywhere = min_gap(bolt, nut)
    ok = flat > 1e-6 and anywhere > 1e-6
    print("%-8.2f %-9.4f %-9.4f %-9.4f %-9.4f %s"
          % (pitch, land, flank, flat, anywhere,
             "ok" if ok else "TOUCHING"))
    if not ok:
        worst.append(pitch)

print("\nPROBE: %s" % ("ok" if not worst else "TOUCHING at %s" % worst))
raise SystemExit(0 if not worst else 1)
