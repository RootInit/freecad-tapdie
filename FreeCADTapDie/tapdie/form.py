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

# Which way the threaded run travels from the selected circle.
BOTH = "Both ways"
FORWARD = "Along axis"
REVERSE = "Against axis"

DIRECTIONS = (BOTH, FORWARD, REVERSE)


def span(direction, length):
    """Axial extent of the threaded run, in coordinates centred on the
    selected circle, as (z_lo, z_hi).

    The anchor is the selected circle itself -- for a face that is its
    midpoint, for an edge it is the edge.  BOTH straddles it, which is right
    for a cylindrical face (the run covers the whole face) and wrong for a
    circular edge at the end of a rod, where half the cutter ends up in open
    air.  That is what FORWARD and REVERSE are for.
    """
    if direction not in DIRECTIONS:
        raise ProfileError(
            "direction %r is not one of %s"
            % (direction, ", ".join(DIRECTIONS)))
    if length <= 0.0:
        raise ProfileError("threaded length must be positive")
    if direction == FORWARD:
        return 0.0, length
    if direction == REVERSE:
        return -length, 0.0
    return -length / 2.0, length / 2.0


class ProfileError(Exception):
    """The requested parameters cannot produce a sweepable cutter."""


def _tan(angle):
    return math.tan(math.radians(angle / 2.0))


def _sec(angle):
    return 1.0 / math.cos(math.radians(angle / 2.0))


def _sin(angle):
    return math.sin(math.radians(angle / 2.0))


def radial_offset(clearance, angle):
    """Radial shift of a V that opens a gap of `clearance` normal to both
    flanks.

    IT IS clearance / sin(angle/2), NOT clearance * sec(angle/2).  The two
    agree at 90 degrees and nowhere else -- at ISO's 60 they differ by 73%
    -- and printed_threads' own spreadsheet comment asserts the sec form
    because 90 degrees is the only angle it ever uses.  This project has now
    been caught by the same 45 degree coincidence three times (see also the
    atan2(dr, dz) flank-angle convention), so derive it rather than trusting
    a remembered formula:

        a flank is  v = (r - apex) * tan(a/2)
        offset normally by c, it becomes  v = (r - apex) * tan(a/2) + c*sec(a/2)
        which crosses v = 0 at  r = apex - c*sec(a/2)/tan(a/2) = apex - c/sin(a/2)
    """
    return clearance / _sin(angle)


def _check_enums(mode, form_name):
    """Validate mode and form_name enums."""
    if mode not in (INTERNAL, EXTERNAL):
        raise ProfileError(
            "mode %r is not %s or %s" % (mode, INTERNAL, EXTERNAL))
    if form_name not in FORMS:
        raise ProfileError(
            "form %r is not one of %s" % (form_name, ", ".join(FORMS)))


def depth(form_name, pitch, angle, mode):
    """Reference depth of the UNTRUNCATED form, ignoring the lands.

    This does NOT position the cutter -- cutter_points anchors the profile on
    the surface being threaded instead (see there for why).  Its only
    production caller is presets.nearest_for_bore, which wants the standard
    ISO depth to reconstruct what minor diameter a tap drill implies.

    For ISO it is the standard fraction of H.  For a near-sharp V it is the
    depth the flanks alone would reach across a whole pitch, which is
    `cut_depth` with both lands set to zero.

    Do not reach for this when you want the depth the cutter really reaches:
    that is `cut_depth`, which accounts for the lands, and the two differ by
    (root_land + crest_land) / (2 tan) -- 0.4mm on a 1.25 pitch printed
    thread, which is most of the depth.
    """
    _check_enums(mode, form_name)
    if form_name == ISO:
        H = pitch * math.sqrt(3.0) / 2.0
        # 17H/24 is the DESIGN depth of an external thread whose root is
        # ROUNDED at H/6.  This cutter cuts a flat root, so its basic depth is
        # 5H/8 in both modes; the external value is kept only because
        # nearest_for_bore's drill estimate is calibrated against real taps.
        return 5.0 * H / 8.0 if mode == INTERNAL else 17.0 * H / 24.0
    return pitch / (2.0 * _tan(angle))


def cut_depth(pitch, angle, root_land, crest_land):
    """Radial depth of the groove, measured from the RELIEVED surface.

    Straight from the profile identity every thread obeys:

        pitch = crest_land + root_land + 2 * depth * tan(angle / 2)

    Clearance is deliberately absent: it shifts the whole profile radially
    (see crest_radius) rather than deepening the groove, so the groove's own
    depth is a pure function of the form.
    """
    return (pitch - crest_land - root_land) / (2.0 * _tan(angle))


def crest_radius(mode, surface_radius, clearance, angle):
    """Radius the thread's crest sits at once clearance is applied.

    Clearance is taken RADIALLY, by relieving the cylinder before threading
    it -- shaving a die's worth off a shaft, or opening a tap's worth out of
    a bore -- and then anchoring the profile on the relieved surface.  This
    is printed_threads' proven arrangement, and the only one that leaves the
    lands alone: a bolt and nut cut with the same settings end up with their
    profiles displaced by 2 * radial_offset, which is a flank gap of exactly
    2 * clearance.

    The alternative -- holding the crest at the original surface and taking
    clearance AXIALLY instead -- was tried and is unusable. It has to come
    out of the crest land, and at 90 degrees it eats 2.83x the clearance
    value: 0.34mm of land for a 0.12mm gap, which is more crest than any
    pitch below M8 has to give. Do not reintroduce it.
    """
    if mode not in (INTERNAL, EXTERNAL):
        raise ProfileError(
            "mode %r is not %s or %s" % (mode, INTERNAL, EXTERNAL))
    offset = radial_offset(clearance, angle)
    if mode == EXTERNAL:
        return surface_radius - offset      # shave the shaft
    return surface_radius + offset          # open out the bore


def required_surface_radius(mode, diameter, pitch, angle, root_land,
                            crest_land, clearance):
    """Radius the cylinder must have for this form to come out at `diameter`.

    The profile is anchored on the surface being threaded, not on the nominal
    diameter, so a bore or shaft of the wrong size yields a correctly shaped
    thread of the wrong SIZE.  This says what size the blank should be:

      * EXTERNAL -- the shaft IS the major diameter, so the answer is just
        diameter/2. Relief then takes the crest to diameter/2 - offset,
        which is what makes the bolt a clearance fit rather than a nominal
        one.
      * INTERNAL -- the bore is the minor diameter. It has to sit one cut
        depth inside the nominal major AND leave room for both parts'
        relief, so that the nut's root lands exactly on the bolt's crest.
        For a 90 degree printed form this is a far larger hole than the ISO
        60 degree tap drill of the same nominal size.
    """
    if mode not in (INTERNAL, EXTERNAL):
        raise ProfileError(
            "mode %r is not %s or %s" % (mode, INTERNAL, EXTERNAL))
    if mode == EXTERNAL:
        return diameter / 2.0
    return (diameter / 2.0
            - cut_depth(pitch, angle, root_land, crest_land)
            - 2.0 * radial_offset(clearance, angle))


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

    # THE SHOULDER IS PINNED TO THE (RELIEVED) SURFACE.  The flank has to
    # reach the cylinder being threaded exactly where the crest land begins;
    # the parallel section then exists purely as overrun PAST the surface,
    # which is the job its docstring describes.
    #
    # This used to anchor the profile on `diameter` and a separately computed
    # depth() instead, and the two disagreed by
    #
    #     crest_land / (2 tan) + clearance * sec
    #
    # Where they disagreed the flank stopped short of the surface and the
    # parallel section covered the difference -- which cuts a flat ANNULAR
    # SHELF, normal to the axis, between every pair of turns, instead of a
    # flank running to the crest.  Measured 0.3697mm of shelf on a nominal
    # M8x1.25 shaft (0.2 from depth() ignoring the lands, 0.1697 from
    # clearance moving the apex radially while the crest stayed put), in
    # both modes, at every pitch, worst on ISO where it reaches 0.96mm.  It
    # is the "left over areas not being booleaned away between pitches" this
    # construction exists to prevent.
    #
    # `diameter` no longer positions anything -- the surface does.  A blank of
    # the wrong size now yields a correctly SHAPED thread of the wrong SIZE,
    # which required_surface_radius() quantifies, rather than a misshapen one
    # of nominal size.
    # Clearance is taken RADIALLY: the cylinder is relieved first (feature.py
    # adds the relief solid to the cutter) and the profile is anchored on the
    # relieved surface.  So the lands come out at exactly the widths asked
    # for, at any pitch, and clearance never competes with them for the
    # pitch budget.  See crest_radius() for why the axial alternative is
    # unusable.
    shoulder = crest_radius(mode, surface_radius, clearance, angle)
    hw = (pitch - crest_land) / 2.0
    tip_half = root_land / 2.0
    run = cut_depth(pitch, angle, root_land, crest_land)

    if mode == INTERNAL:
        tip = shoulder + run
        # `far` is measured from the ORIGINAL surface, so the cutter still
        # clears the unrelieved bore by the full overrun.
        far = surface_radius - overrun
        if far <= 0.0:
            raise ProfileError(
                "cutter overrun %.4f reaches through the axis from a bore at "
                "r=%.4f" % (overrun, surface_radius))
    else:
        tip = shoulder - run
        far = surface_radius + overrun
        if tip <= 0.0:
            raise ProfileError(
                "thread depth %.4f plus clearance is deeper than the shaft "
                "radius %.4f" % (run, surface_radius))

    return [
        (tip, tip_half),
        (shoulder, hw),
        (far, hw),
        (far, -hw),
        (shoulder, -hw),
        (tip, -tip_half),
    ]
