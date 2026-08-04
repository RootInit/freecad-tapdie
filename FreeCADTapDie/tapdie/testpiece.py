"""A small printable pair for checking settings before committing to a part.

The point of a test coupon is to answer one question -- "do MY settings, on MY
printer, produce a thread that actually screws together?" -- so it is built by
running the ordinary cutter over primitive blanks, not by any shortcut of its
own.  If the coupon and the real thread came from different code they would be
free to disagree, which would make the coupon worse than useless: it would
give a confident answer about the wrong geometry.

The blanks are sized so the cutter has nothing to correct.  The male blank is
exactly `Diameter`, and the female bore is exactly what
form.required_surface_radius asks for, so neither piece is relieved and both
come out at nominal -- and if they then do not mate on the printer, the
setting to change is the clearance, not the blank.

Both pieces stand on the bed axis-vertical, which is the orientation the 90
degree form is designed for: every flank sits at the 45 degree overhang limit
only when the thread is printed this way up.
"""

import math

import FreeCAD as App
import Part

from . import api, form, presets

# Wall thickness around the thread, in mm. Enough to be stiff at any size
# without making the coupon a brick.
WALL = 3.0
# Flange under the male post: something to grip, and a flat foot for the bed.
FLANGE = 2.0
# Turns of engagement. Fewer than three and a bad fit can still feel fine;
# many more just costs print time for no extra information.
TURNS = 4.0
MIN_THREAD = 4.0
MAX_THREAD = 12.0
# Gap between the two pieces on the bed.
SPACING = 4.0


def thread_length(pitch):
    """Enough turns to be conclusive, without printing a bolt."""
    return max(MIN_THREAD, min(MAX_THREAD, TURNS * pitch))


def _hex_prism(across_flats, height, origin):
    """A hex so the coupon can be turned by hand. `across_flats` is the
    distance between opposite FACES, which is what a spanner measures; the
    polygon needs the circumradius, which is 2/sqrt(3) of the apothem."""
    circumradius = across_flats / math.sqrt(3.0)
    points = []
    for i in range(6):
        angle = math.radians(60.0 * i)
        points.append(App.Vector(circumradius * math.cos(angle),
                                 circumradius * math.sin(angle), 0.0))
    points.append(points[0])
    face = Part.Face(Part.makePolygon(points))
    solid = face.extrude(App.Vector(0, 0, height))
    solid.translate(origin)
    return solid


def _cylindrical_face(obj, radius):
    for i, face in enumerate(obj.Shape.Faces):
        surface = face.Surface
        if (isinstance(surface, Part.Cylinder)
                and abs(surface.Radius - radius) < 1e-6):
            return "Face%d" % (i + 1)
    raise api.ThreadError(
        "test piece blank has no cylindrical face at r=%.4f" % radius)


def _profile(params, mode):
    """Angle and both lands, resolved exactly as feature.py will resolve them.

    ISO swaps its two truncations between internal and external, so this has
    to be asked per mode rather than computed once for the pair.
    """
    form_name = params.get("ThreadForm", form.PRINTED)
    if form_name == form.CUSTOM:
        return (params["Angle"], params["RootLand"], params["CrestLand"])
    defaults = presets.form_defaults(form_name, params["Pitch"], mode)
    return (defaults["angle"], defaults["root_land"],
            defaults["crest_land"])


def female_bore_radius(params):
    """Bore the female blank needs for the thread to come out at nominal."""
    angle, root_land, crest_land = _profile(params, form.INTERNAL)
    return form.required_surface_radius(
        form.INTERNAL, params["Diameter"], params["Pitch"], angle,
        root_land, crest_land, params["Clearance"])


def build(doc, params, created=None, origin=None):
    """Build the male/female pair in `doc`.  Returns (male_cut, female_cut).

    `params` is the task panel's own override dict, so the coupon carries
    every setting the real thread does -- form, pitch, clearances, handedness
    and start angle included.  Mode, Length and Direction are the only keys
    replaced, because each piece needs its own.

    NO TRANSACTION: the caller owns one, and everything created is appended
    to `created` so a Cancel can take it all back out again.
    """
    if created is None:
        created = []
    if origin is None:
        origin = App.Vector(0, 0, 0)

    diameter = params["Diameter"]
    pitch = params["Pitch"]
    length = thread_length(pitch)
    radius = diameter / 2.0
    bore = female_bore_radius(params)
    if bore <= 0.0:
        raise api.ThreadError(
            "a %.2fmm test thread needs a %.2fmm bore, which is not a hole"
            % (diameter, 2.0 * bore))

    across = diameter + 2.0 * WALL
    # A hex with a vertex at azimuth 0 spans its CIRCUMRADIUS either side of
    # its centre, not its across-flats. Both pieces are therefore placed by
    # their own left edge, so `origin` means "the coupon starts here" and the
    # caller can drop it beside the part without it reaching back over it.
    reach = across / math.sqrt(3.0)
    shared = dict(params)
    for key in ("Mode", "Length", "Direction", "SurfaceRadius"):
        shared.pop(key, None)

    # ---- male: a post on a flange -------------------------------------
    # The flange is deliberately wider than the post, so the run's lower end
    # ABUTS material. That exercises the free/abutting detection the same way
    # a real bolt against a head does, and leaves the top end free to take
    # the lead-in chamfer that makes it possible to start by hand.
    male_at = origin + App.Vector(reach, 0.0, 0.0)
    post = Part.makeCylinder(radius, length + FLANGE, male_at)
    flange = _hex_prism(across, FLANGE, male_at)
    male = doc.addObject("Part::Feature", "TestPieceMale")
    male.Shape = post.fuse(flange).removeSplitter()
    doc.recompute()
    created.append(male)

    overrides = dict(shared)
    overrides.update({"Mode": form.EXTERNAL, "Length": length,
                      "Direction": form.FORWARD})
    male_cutter, male_cut = api.build_thread(
        doc, male, _cylindrical_face(male, radius), overrides, created)
    # Label only the finished Cut. Labelling the blank too made FreeCAD
    # uniquify the second one, so the tree showed "M8 x 1.25" beside a
    # baffling "M8 x 1.001".
    male_cut.Label = "Test piece male M%g x %g" % (diameter, pitch)

    # ---- female: a hex nut, bored through ------------------------------
    female_at = male_at + App.Vector(2.0 * reach + SPACING, 0.0, 0.0)
    height = length + 2.0 * FLANGE
    body = _hex_prism(across, height, female_at)
    hole = Part.makeCylinder(bore, height, female_at)
    female = doc.addObject("Part::Feature", "TestPieceFemale")
    female.Shape = body.cut(hole)
    doc.recompute()
    created.append(female)

    overrides = dict(shared)
    overrides.update({"Mode": form.INTERNAL, "Length": height,
                      "Direction": form.BOTH})
    female_cutter, female_cut = api.build_thread(
        doc, female, _cylindrical_face(female, bore), overrides, created)
    female_cut.Label = "Test piece female M%g x %g" % (diameter, pitch)

    doc.recompute()
    for obj, what in ((male_cut, "male"), (female_cut, "female")):
        if obj.Shape.isNull() or not obj.Shape.isValid():
            raise api.ThreadError("test piece %s did not build" % what)
    return male_cut, female_cut
