"""Orchestration: selection in, threaded solid out.

This module must never import FreeCADGui -- it is what makes the whole plugin
testable headlessly.
"""

import FreeCAD as App

from . import feature, form, presets, selection


class ThreadError(Exception):
    """The thread could not be created."""


def defaults_for(circle):
    """Sensible starting parameters for a resolved selection."""
    mode = circle.mode or form.INTERNAL
    if mode == form.INTERNAL:
        diameter, pitch = presets.nearest_for_bore(circle.radius * 2.0)
    else:
        diameter, pitch = presets.nearest_for_shaft(circle.radius * 2.0)
    return {
        "Mode": mode,
        "Diameter": diameter,
        "Pitch": pitch,
        "Length": circle.length,
        "SurfaceRadius": circle.radius,
    }


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


def create_thread(doc, base, sub_name, overrides=None):
    """Thread `base` at `sub_name`.  Returns (cutter, cut).

    Everything is done inside one undo transaction so a single Ctrl-Z removes
    both objects rather than leaving an orphaned cutter.
    """
    circle = selection.resolve(base, sub_name)
    params = defaults_for(circle)
    params.update(overrides or {})

    doc.openTransaction("Thread")
    created = []
    try:
        cutter_obj = feature.make_cutter(doc)
        created.append(cutter_obj)
        for key, value in params.items():
            setattr(cutter_obj, key, value)

        # The link is what creates the dependency, so the cutter recomputes
        # (and repositions) whenever the base moves.
        cutter_obj.AttachedTo = base
        cutter_obj.LocalPlacement = local_frame(base, circle)
        doc.recompute()

        if not cutter_obj.Shape.isValid() or not cutter_obj.Shape.Solids:
            raise ThreadError(
                "cutter did not build; check Diameter, Pitch and the lands")

        cut = doc.addObject("Part::Cut", "Thread")
        created.append(cut)
        cut.Base = base
        cut.Tool = cutter_obj
        doc.recompute()

        # Part::Cut is FreeCAD's, so it cannot be guarded from inside.  A
        # helical boolean is known to return one closed solid that is
        # nevertheless invalid while still reporting Up-to-date.
        if not cut.Shape.isValid():
            raise ThreadError("boolean produced an invalid solid")
        if len(cut.Shape.Solids) != 1:
            raise ThreadError(
                "boolean produced %d solids, expected 1"
                % len(cut.Shape.Solids))

        doc.commitTransaction()
        return cutter_obj, cut
    except Exception:
        doc.abortTransaction()
        for obj in reversed(created):
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
        doc.recompute()
        raise
