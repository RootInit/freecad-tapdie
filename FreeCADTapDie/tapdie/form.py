"""Cutter profile mathematics.

Pure Python -- this module must never import FreeCAD, so it stays fast to test.

The cutter is a truncated V that runs PARALLEL to the axis once past its
shoulder.  The parallel section is what lets it clear the crest without the
swept solid ever exceeding one pitch in width -- a plain triangle would have to
be exactly one pitch wide at the crest radius, which is the tangency case where
consecutive turns of the sweep touch each other.
"""

import math

INTERNAL = "Internal"
EXTERNAL = "External"

PRINTED = "Printed 90"
ISO = "ISO metric 60"
CUSTOM = "Custom"

FORMS = (PRINTED, ISO, CUSTOM)


class ProfileError(Exception):
    """The requested parameters cannot produce a sweepable cutter."""


def _tan(angle):
    return math.tan(math.radians(angle / 2.0))


def _sec(angle):
    return 1.0 / math.cos(math.radians(angle / 2.0))


def _check_enums(mode, form_name):
    """Validate mode and form_name enums."""
    if mode not in (INTERNAL, EXTERNAL):
        raise ProfileError(
            "mode %r is not %s or %s" % (mode, INTERNAL, EXTERNAL))
    if form_name not in FORMS:
        raise ProfileError(
            "form %r is not one of %s" % (form_name, ", ".join(FORMS)))


def depth(form_name, pitch, angle, mode):
    """Radial depth of the thread.

    ISO is a truncated V with standard H/8 and H/4 truncations, so its depth
    is a fixed fraction of H.  The printed form is a near-sharp V, which spends
    the whole pitch on flanks -- so its depth follows directly from the angle.
    """
    _check_enums(mode, form_name)
    if form_name == ISO:
        H = pitch * math.sqrt(3.0) / 2.0
        return 5.0 * H / 8.0 if mode == INTERNAL else 17.0 * H / 24.0
    return pitch / (2.0 * _tan(angle))


def cutter_points(mode, form_name, diameter, pitch, angle, root_land,
                  crest_land, clearance, surface_radius, overrun):
    """Six corners of the swept cutter as (radius, axial_offset) tuples.

    Ordered tip -> shoulder -> far -> far -> shoulder -> tip, which is a simple
    closed polygon in both modes.

    `root_land` is the flat at the tip (the thread's root); `crest_land` is the
    flat left at the surface (the thread's crest).  They are separate because
    ISO truncates asymmetrically -- H/8 at one end, H/4 at the other -- and no
    single value satisfies both.
    """
    _check_enums(mode, form_name)
    if overrun <= 0.0:
        raise ProfileError(
            "overrun %.4f must be positive; the cutter has to reach past the "
            "surface it is cutting" % overrun)
    if pitch <= 0.0:
        raise ProfileError("pitch must be positive")
    for name, value in (("root_land", root_land), ("crest_land", crest_land)):
        if value <= 0.0:
            raise ProfileError(
                "%s is %.4f; a mathematically sharp edge is the tangency case "
                "where consecutive turns of the sweep touch" % (name, value))
    if root_land + crest_land >= pitch:
        raise ProfileError(
            "root_land %.4f plus crest_land %.4f leaves no flank within the "
            "%.4f pitch" % (root_land, crest_land, pitch))
    if not 10.0 < angle < 170.0:
        raise ProfileError("included angle %.1f is out of range" % angle)

    tan, sec = _tan(angle), _sec(angle)
    hw = (pitch - crest_land) / 2.0
    tip_run = (root_land / 2.0) / tan
    flank_run = hw / tan
    d = depth(form_name, pitch, angle, mode)

    if mode == INTERNAL:
        apex = diameter / 2.0 + clearance * sec
        tip = apex - tip_run
        shoulder = apex - flank_run
        if shoulder < surface_radius:
            raise ProfileError(
                "cutter shoulder at r=%.4f cannot reach the bore at r=%.4f; "
                "increase Diameter or Pitch" % (shoulder, surface_radius))
        far = min(shoulder, surface_radius) - overrun
        if far <= 0.0:
            raise ProfileError("cutter reaches through the axis")
    else:
        apex = diameter / 2.0 - d - clearance * sec
        tip = apex + tip_run
        shoulder = apex + flank_run
        if shoulder > surface_radius:
            raise ProfileError(
                "cutter shoulder at r=%.4f overshoots the surface at r=%.4f; "
                "reduce Diameter or Pitch" % (shoulder, surface_radius))
        far = max(shoulder, surface_radius) + overrun
        if tip <= 0.0:
            raise ProfileError("thread is deeper than the shaft radius")

    half_root = root_land / 2.0
    return [
        (tip, half_root),
        (shoulder, hw),
        (far, hw),
        (far, -hw),
        (shoulder, -hw),
        (tip, -half_root),
    ]
