"""ISO coarse-pitch table and the diameter lookups that use it.

Pure Python -- no FreeCAD import.
"""

import math

from . import form

# (nominal diameter mm, coarse pitch mm), ISO 261.
ISO_COARSE = (
    (3.0, 0.50), (4.0, 0.70), (5.0, 0.80), (6.0, 1.00), (7.0, 1.00),
    (8.0, 1.25), (10.0, 1.50), (12.0, 1.75), (14.0, 2.00), (16.0, 2.00),
    (18.0, 2.50), (20.0, 2.50), (22.0, 2.50), (24.0, 3.00),
)


def nearest_for_bore(bore_diameter):
    """Best (diameter, pitch) for a detected bore.

    A tap drill is deliberately larger than the theoretical minor diameter --
    it targets roughly 75% thread engagement -- so this reconstructs the minor
    diameter each table entry implies and takes the closest match.  Choosing
    the entry whose NOMINAL diameter is nearest picks the wrong, smaller size
    on every entry in the table, because the pitch spacing between adjacent
    sizes is comparable to the depth being reconstructed.

    The result is a starting guess for the user to confirm, not an exact
    relationship: residual error runs to roughly a third of a millimetre.
    """
    def error(entry):
        diameter, pitch = entry
        minor = diameter - 2.0 * form.depth(
            form.ISO, pitch, 60.0, form.INTERNAL)
        return abs(bore_diameter - minor)

    return min(ISO_COARSE, key=error)


def nearest_for_shaft(shaft_diameter):
    """Best (diameter, pitch) for a detected shaft.

    A die cuts into an existing OD, so the shaft IS the major diameter and a
    plain nearest-nominal match is correct here.
    """
    return min(ISO_COARSE, key=lambda e: abs(e[0] - shaft_diameter))


# One extrusion width: the floor for any modelled land, printed or not.
NOZZLE = 0.4
# printed_threads' near-sharp land, as a pure fraction of pitch. Correct at
# the 3.8mm pitch it was reverse-engineered from (0.021 x 3.8 = 0.08mm), but
# a PURE fraction does not survive a change of pitch: at 1.25mm it collapses
# to 0.026mm, about 1/15th of an extrusion width -- a knife edge the nozzle
# cannot resolve, so the thread prints without the flat bottom it was
# designed to have. Floored at NOZZLE below.
LAND_FRACTION = 0.021
# Never let a single land exceed this share of the pitch. NOT optional:
# form.cutter_points rejects root_land + crest_land >= pitch, and an
# unconditional NOZZLE floor on BOTH lands sums to 0.8mm, which alone
# already breaks every pitch <= 0.8mm (M5 and below, including M4/M3). With
# this cap the two lands can sum to at most 2 * LAND_CAP * pitch = 0.7 x
# pitch, which can never trip that guard.
LAND_CAP = 0.35


def printed_land(pitch, angle=90.0):
    """Land width for the printed form: one extrusion width where the pitch
    can afford it, a near-sharp V where it cannot.

    THE LAND YIELDS TO THE DEPTH. Every term competes for the same budget,

        pitch = crest_land + root_land + 2 * depth * tan(angle / 2)

    so a land floored unconditionally at NOZZLE buys its printable flat
    straight out of the groove. Measured across the whole ISO coarse table,
    an unconditional floor left the thread shallower than one extrusion
    width at EVERY size up to and including M10 -- 0.105mm of depth on
    M4x0.7, a quarter of a nozzle, which no slicer will resolve. That
    inverts the floor's own purpose: it guarantees a printable flat by
    producing an unprintable groove. Depth is what carries the load, so
    depth wins.

    The result keeps the NOZZLE floor everywhere it is actually affordable
    (M12 and up at 90 degrees) and falls back towards printed_threads' own
    near-sharp 0.021 x pitch below that -- which is what printed_threads
    itself runs, at 0.08mm, well under one extrusion width, and prints fine.
    """
    tan = math.tan(math.radians(angle / 2.0))
    # What the pitch can spare while still leaving one extrusion width of
    # groove. Goes negative at fine pitches, where no land is affordable.
    for_depth = (pitch - 2.0 * NOZZLE * tan) / 2.0
    land = min(max(LAND_FRACTION * pitch, NOZZLE), for_depth,
               LAND_CAP * pitch)
    # Never below the near-sharp fraction, and never zero or negative:
    # form.cutter_points rejects a mathematically sharp edge outright.
    return max(land, LAND_FRACTION * pitch)


def form_defaults(form_name, pitch, mode=form.INTERNAL):
    """Angle and the two land WIDTHS (mm) a preset imposes at this pitch.

    ISO's basic profile truncates the fundamental triangle so that the flat
    at the MAJOR diameter is P/8 and the flat at the MINOR diameter is P/4.
    Which of those is the crest and which the root DEPENDS ON THE MODE, and
    they are not interchangeable:

        internal -- crest is at the minor (P/4), root at the major (P/8)
        external -- crest is at the major (P/8), root at the minor (P/4)

    This used to return the internal assignment in both modes, so every ISO
    external thread came out with its two truncations swapped: a P/4 crest
    where the standard wants P/8. The depth is unaffected (it depends only
    on the sum) which is why the error survived -- nothing that measured
    depth could see it.

    Both are pure fractions of pitch that already scale correctly at any
    pitch, so they are used as-is, unfloored and uncapped: this is the
    standard truncation, not a printability patch.

    The printed form's land comes from printed_land(), which keeps the
    one-extrusion-width floor wherever the pitch can afford it and yields to
    thread depth where it cannot -- see there for the measurements.

    One correction to the record: the floor is NOT, as an earlier version of
    this docstring claimed, the fix for the "does not have a flat bottom
    profile" report. That was about the cutter's overrun gouging a hex head,
    and was fixed by the free/abutting end detection in feature.py. Nothing
    about land width was ever involved.
    """
    if form_name == form.ISO:
        if mode not in (form.INTERNAL, form.EXTERNAL):
            raise ValueError(
                "mode %r is not %s or %s"
                % (mode, form.INTERNAL, form.EXTERNAL))
        at_major, at_minor = pitch / 8.0, pitch / 4.0
        if mode == form.INTERNAL:
            root, crest = at_major, at_minor
        else:
            root, crest = at_minor, at_major
        return {"angle": 60.0, "root_land": root, "crest_land": crest}
    if form_name == form.PRINTED:
        land = printed_land(pitch)
        return {"angle": 90.0, "root_land": land, "crest_land": land}
    raise ValueError(
        "form %r has no preset; expected %s or %s"
        % (form_name, form.PRINTED, form.ISO))
