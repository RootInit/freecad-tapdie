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


def form_defaults(form_name):
    """Angle and the two land fractions a preset imposes.

    Fractions multiply the pitch.  ISO's basic profile truncates the
    fundamental triangle by H/8 at one end and H/4 at the other, which works
    out to flats of P/8 at the root and P/4 at the crest -- asymmetric, so the
    two fractions genuinely differ.  The printed form uses one near-sharp land
    at both ends: 0.021 reproduces the 0.08 mm land at a 3.8 mm pitch that
    printed_threads measures and prints successfully.
    """
    if form_name == form.ISO:
        return {"angle": 60.0, "root_fraction": 0.125, "crest_fraction": 0.25}
    if form_name == form.PRINTED:
        return {"angle": 90.0, "root_fraction": 0.021, "crest_fraction": 0.021}
    raise ValueError(
        "form %r has no preset; expected %s or %s"
        % (form_name, form.PRINTED, form.ISO))
