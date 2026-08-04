"""Orchestration: selection in, threaded solid out.

This module must never import FreeCADGui -- it is what makes the whole plugin
testable headlessly.
"""

import FreeCAD as App

from . import feature, form, presets, selection


class ThreadError(Exception):
    """The thread could not be created."""


# How far the thread a cutter really produces may drift from the Diameter
# asked for before it is worth saying so, in mm. form.achieved_diameter and
# form.required_surface_radius are exact inverses -- measured to 1e-9 across
# the whole ISO coarse table, both modes, both forms -- so any drift reported
# is real. The threshold is not there to absorb error but to stay quiet on
# the commonest legitimate case: a standard 6.6mm M8 tap drill yields 8.08mm
# on the printed form, and nagging about that would train the user to ignore
# the line entirely.
DIAMETER_TOLERANCE = 0.1


def defaults_for(circle):
    """Sensible starting parameters for a resolved selection."""
    mode = circle.mode or form.INTERNAL
    if mode == form.INTERNAL:
        diameter, pitch = presets.nearest_for_bore(circle.radius * 2.0)
    else:
        diameter, pitch = presets.nearest_for_shaft(circle.radius * 2.0)
    # The cutter's parallel section runs `Overrun` past the surface it is
    # cutting. For a BORE that direction is inward, towards the axis, so a
    # fixed 1.0mm reached straight through the middle of anything under
    # r=1.0 and form.cutter_points rejected it outright -- with no dialog
    # control able to fix it, since Overrun was not exposed. Half the radius
    # always clears the axis, and for a shaft the overrun runs outward where
    # nothing constrains it.
    overrun = 1.0 if mode == form.EXTERNAL else min(1.0, 0.5 * circle.radius)
    return {
        "Mode": mode,
        "Diameter": diameter,
        "Pitch": pitch,
        "Length": circle.length,
        "Direction": circle.direction,
        "SurfaceRadius": circle.radius,
        "Overrun": overrun,
    }


def diameter_note(cutter_obj):
    """What this cutter will really produce, when that is not what was asked.

    Returns None when the two agree to within DIAMETER_TOLERANCE.

    `Diameter` positions nothing -- form.cutter_points anchors the profile on
    the SURFACE and never reads it (measured: byte-identical profiles for 8.0
    and 24.0). form.py calls Diameter "a check, not a driver", but the check
    was never performed anywhere, so the field was simply inert: a user
    threading a 20mm shaft could ask for 16 and get 20 in silence. This is
    that check.
    """
    mode = cutter_obj.Mode
    # Measure against the radius the cutter really anchors on, which honours
    # Diameter wherever material can be removed to reach it. What is left is
    # only the direction no cutting tool can do -- a thread larger than the
    # shaft, or smaller than the bore -- so anything reported here is a
    # request that was genuinely clamped, not a rounding difference.
    anchor = form.effective_surface_radius(
        mode, cutter_obj.Diameter.Value, cutter_obj.Pitch.Value,
        cutter_obj.Angle.Value, cutter_obj.RootLand.Value,
        cutter_obj.CrestLand.Value, cutter_obj.Clearance.Value,
        cutter_obj.SurfaceRadius.Value)
    got = form.achieved_diameter(
        mode, cutter_obj.Pitch.Value, cutter_obj.Angle.Value,
        cutter_obj.RootLand.Value, cutter_obj.CrestLand.Value,
        cutter_obj.Clearance.Value, anchor)
    want = cutter_obj.Diameter.Value
    if abs(got - want) <= DIAMETER_TOLERANCE:
        return None
    needed = 2.0 * form.required_surface_radius(
        mode, want, cutter_obj.Pitch.Value, cutter_obj.Angle.Value,
        cutter_obj.RootLand.Value, cutter_obj.CrestLand.Value,
        cutter_obj.Clearance.Value)
    surface = "shaft" if mode == form.EXTERNAL else "bore"
    direction = "smaller" if mode == form.EXTERNAL else "larger"
    return ("This cuts a %.2fmm thread, not %.2fmm: a %.2fmm thread needs a "
            "%.2fmm %s and the selected one is %.2fmm. Cutting only removes "
            "material, so the thread can go %s than the %s but not the other "
            "way."
            % (got, want, want, needed, surface,
               2.0 * cutter_obj.SurfaceRadius.Value, direction, surface))


def local_frame(base, circle):
    """The circle's frame expressed in the base part's local coordinates.

    `circle` was read off `base.Shape`, which already has the base's placement
    baked in, so the global frame must be pulled back through it.  Storing the
    LOCAL frame is what lets the cutter follow the base under rotation as well
    as translation.
    """
    rotation = App.Rotation(App.Vector(0, 0, 1), circle.axis)
    world = App.Placement(circle.centre, rotation)
    return base.Placement.inverse().multiply(world)


def apply_params(cutter_obj, params):
    """Set every parameter on `cutter_obj`, in an order that survives presets.

    ThreadForm, Pitch and Mode all re-trigger feature.py's _apply_preset(),
    which overwrites Angle/RootLand/CrestLand -- so those (plus Diameter,
    which the profile math also treats as structural) must be set FIRST.
    Applying params in whatever order the caller's dict happened to iterate
    silently discarded an explicit Angle/RootLand/CrestLand override whenever
    a structural key came later; a task-panel submission that sends every
    field at once hits this on every call.  Pops from a local copy, not
    `params` itself, since a caller may still hold a reference to it.
    """
    STRUCTURAL = ("Mode", "ThreadForm", "Pitch", "Diameter")
    remaining = dict(params)
    for key in STRUCTURAL:
        if key in remaining:
            setattr(cutter_obj, key, remaining.pop(key))
    for key, value in remaining.items():
        setattr(cutter_obj, key, value)


def _check_recomputed(obj, what):
    """Raise unless `obj`'s last recompute actually succeeded.

    A NULL shape is not a reliable signal on its own.  When execute() raises
    on an object that has ALREADY built once -- which is every parameter
    change in the live preview -- FreeCAD keeps the previous shape rather
    than nulling it, and marks the object Touched/Invalid instead.  Checking
    only the shape therefore reported success while showing stale geometry:
    the preview silently kept displaying the last good thread no matter what
    the user typed.  Found by driving the task panel in an offscreen GUI;
    no headless test could see it, because the one-shot create path always
    starts from an object with no previous shape.
    """
    state = set(obj.State)
    if "Invalid" in state or "Touched" in state or "Error" in state:
        # feature.ThreadCutter records what execute() actually raised, because
        # FreeCAD swallows it. Prefer that over guessing: this used to tell a
        # user whose 0.9mm bore was smaller than the 1.0mm Overrun to "check
        # Diameter, Pitch and the lands", which cannot fix it. A Part::Cut has
        # no Proxy and still gets the generic advice, which is all there is
        # for a boolean FreeCAD owns.
        detail = getattr(getattr(obj, "Proxy", None), "last_error", None)
        if detail:
            raise ThreadError("%s did not build: %s" % (what, detail))
        # Same leading phrase as the shape checks below, deliberately: which
        # of the two guards fires is an implementation detail, and callers
        # (and tests) should not have to match on both wordings.
        raise ThreadError(
            "%s did not build (recompute left it %s); check Diameter, Pitch "
            "and the lands" % (what, ", ".join(sorted(state))))


def _validate(cutter_obj, cut):
    """Raise ThreadError unless both the cutter and the boolean came out."""
    _check_recomputed(cutter_obj, "cutter")
    # Check isNull() FIRST: when execute() raises on a FRESH object, obj.Shape
    # is left NULL, and Shape.isNull() -- unlike isValid() and Solids -- is
    # safe to call on it.  Shape.isValid() on a null shape raises its own
    # native OCCError ("...NULL shape") before the `or` below is ever
    # reached, which meant a bad parameter surfaced FreeCAD's cryptic OCC
    # string to the user instead of this diagnostic.
    shape = cutter_obj.Shape
    if shape.isNull() or not shape.isValid() or not shape.Solids:
        raise ThreadError(
            "cutter did not build; check Diameter, Pitch and the lands")
    if cut is None:
        return
    _check_recomputed(cut, "boolean")
    # Part::Cut is FreeCAD's, so it cannot be guarded from inside.  A helical
    # boolean is known to return one closed solid that is nevertheless
    # invalid while still reporting Up-to-date.
    if cut.Shape.isNull() or not cut.Shape.isValid():
        raise ThreadError("boolean produced an invalid solid")
    if len(cut.Shape.Solids) != 1:
        raise ThreadError(
            "boolean produced %d solids, expected 1" % len(cut.Shape.Solids))


def build_cutter(doc, base, sub_name, overrides=None, created=None):
    """Create and parameterise the cutter ALONE.  No boolean.

    This is what the task panel previews: the cutter solid is exactly the
    material the thread would remove, so showing it translucent-red over the
    untouched part says the same thing as performing the cut, without
    consuming the part or needing to be undone if the user changes their
    mind.  It is also how FreeCAD's own Part tools preview.

    NO transaction and NO cleanup: the caller owns both.

    `created` is an optional list this appends each new object to as it goes,
    so a caller can clean up precisely after a mid-way failure.  Never
    reconstruct that list by scanning the document for likely-looking names:
    "Thread" and "ThreadCutter" also match every object a PREVIOUS successful
    call left behind, and deleting those would destroy the user's work.
    """
    circle = selection.resolve(base, sub_name)
    params = defaults_for(circle)
    params.update(overrides or {})

    if created is None:
        created = []

    cutter_obj = feature.make_cutter(doc)
    created.append(cutter_obj)
    apply_params(cutter_obj, params)

    # The link is what creates the dependency, so the cutter recomputes (and
    # repositions) whenever the base moves.
    cutter_obj.AttachedTo = base
    cutter_obj.LocalPlacement = local_frame(base, circle)
    doc.recompute()
    _validate(cutter_obj, None)
    return cutter_obj


def apply_cut(doc, base, cutter_obj, created=None):
    """Perform the boolean, consuming `base` with `cutter_obj`.

    Separate from build_cutter so the panel can leave this until the user
    actually commits.  FreeCAD hides Base and Tool as soon as the Part::Cut
    exists, which is why doing it during a preview would make the part
    disappear the moment the dialog opened.
    """
    if created is None:
        created = []
    cut = doc.addObject("Part::Cut", "Thread")
    created.append(cut)
    cut.Base = base
    cut.Tool = cutter_obj
    doc.recompute()
    _validate(cutter_obj, cut)
    return cut


def build_thread(doc, base, sub_name, overrides=None, created=None):
    """Create the cutter and the boolean.  Returns (cutter, cut)."""
    if created is None:
        created = []
    cutter_obj = build_cutter(doc, base, sub_name, overrides, created)
    cut = apply_cut(doc, base, cutter_obj, created)
    return cutter_obj, cut


def update_thread(cutter_obj, cut, overrides):
    """Re-parameterise an existing cutter in place and revalidate.

    This is what makes a live preview cheap: the objects and the base link
    stay put, so only the sweep is rebuilt.
    """
    apply_params(cutter_obj, overrides)
    cutter_obj.Document.recompute()
    _validate(cutter_obj, cut)


def create_thread(doc, base, sub_name, overrides=None):
    """Thread `base` at `sub_name`.  Returns (cutter, cut).

    Everything is done inside one undo transaction, so the tree shows one
    "Thread" step rather than two unrelated additions, and ONE Ctrl-Z removes
    the whole thread.

    That last part was not always true. This docstring used to record it as a
    known limitation -- one Ctrl-Z left the Part::Cut behind with its Tool
    gone -- and blamed the DIAMOND this builds (the cutter links to `base`
    via AttachedTo while the Cut consumes both). That diagnosis was wrong,
    and wrong in the way this project keeps being wrong: a plausible mental
    model written down as fact. Bisection (tools/probe_undo_cause.py) shows
    the identical diamond added to a minimal fixture undoes perfectly, and
    removing AttachedTo from this very path changes nothing.

    The real cause was in cutter.build: it created AND closed a scratch
    document inside execute(), which destroys the caller's open transaction.
    Fixed there by reusing one long-lived document. The damage was also worse
    than recorded -- the base part stayed hidden after the undo, so the user
    was left with an invisible part and a broken boolean.
    """
    created = []
    doc.openTransaction("Thread")
    try:
        result = build_thread(doc, base, sub_name, overrides, created)
        doc.commitTransaction()
        return result
    except Exception:
        doc.abortTransaction()
        discard(doc, *reversed(created))
        raise


def discard(doc, *objects):
    """Remove `objects`, tolerating any that are already gone.

    abortTransaction usually takes newly created objects with it, but it is
    not guaranteed to when the failure happened mid-recompute, and an
    orphaned cutter left in the tree is worse than a no-op removal.
    """
    for obj in objects:
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass
    doc.recompute()
