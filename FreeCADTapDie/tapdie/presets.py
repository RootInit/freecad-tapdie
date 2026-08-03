"""ISO coarse-pitch table and the diameter lookups that use it.

Pure Python -- no FreeCAD import.
"""

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


def form_defaults(form_name, pitch):
    """Angle and the two land WIDTHS (mm) a preset imposes at this pitch.

    ISO's basic profile truncates the fundamental triangle by H/8 at the
    root and H/4 at the crest -- a pure fraction of pitch that already
    scales correctly at any pitch, so it is used as-is, unfloored and
    uncapped: this is the standard truncation, not a printabilty patch.

    The printed form uses one near-sharp land at both ends, floored at one
    extrusion width (NOZZLE) so it survives a fine pitch, and capped at
    LAND_CAP x pitch so the floor can never trip form.cutter_points' "no
    flank left within the pitch" guard (see LAND_CAP above). This means the
    printed form's land at a 3.8mm pitch is now 0.4mm, not the 0.08mm
    printed_threads measures -- a deliberate change, not a regression: a
    0.08mm land is below one extrusion width and was exactly the "does not
    have a flat bottom profile" defect this floor exists to fix. Do not
    restore 0.08mm at 3.8mm pitch without revisiting why the floor exists.
    """
    if form_name == form.ISO:
        return {"angle": 60.0,
                "root_land": pitch / 8.0,
                "crest_land": pitch / 4.0}
    if form_name == form.PRINTED:
        land = min(max(LAND_FRACTION * pitch, NOZZLE), LAND_CAP * pitch)
        return {"angle": 90.0, "root_land": land, "crest_land": land}
    raise ValueError(
        "form %r has no preset; expected %s or %s"
        % (form_name, form.PRINTED, form.ISO))
