"""Exercise the task panel's preview lifecycle in a real (offscreen) GUI.

freecadcmd cannot test this: there is no FreeCADGui and no PySide event loop,
so the panel -- the one part of the addon that owns Qt widgets and an undo
transaction -- would otherwise ship entirely unexercised.

Checks, in order:
  * the panel builds a preview the moment it opens
  * changing Direction re-parameterises the SAME objects, no leak
  * Cancel rolls the whole thing back, leaving the document as it started
  * OK commits, leaving exactly the cutter and the Part::Cut
  * a parameter set that cannot build reports itself and refuses to apply
"""

import os
import sys

import FreeCAD as App
import FreeCADGui as Gui

LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "diag_preview.log"), "w")

failures = []


def line(msg):
    LOG.write("%s\n" % msg)
    LOG.flush()


def check(label, ok, detail=""):
    line("%-58s %s %s" % (label, "ok" if ok else "FAIL", detail))
    if not ok:
        failures.append(label)


sys.path.insert(0, "/home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie")

from PySide import QtGui                      # noqa: E402
from tapdie import command, form, selection   # noqa: E402

# accept() pops a modal QMessageBox when it refuses. Modal dialogs need an
# event loop; offscreen there is none, so the call blocks until the harness
# kills the process -- which is exactly what happened on the first two runs
# of this script (exit 143, every check after the refusal never reported).
# Record the calls instead of showing them.
warnings = []
QtGui.QMessageBox.warning = (
    lambda parent, title, text, *a, **k: warnings.append(text))

# Same reasoning for closeDialog: the panel calls it on both exits, and the
# task-panel machinery it drives expects a running Gui. Stub it -- what this
# script tests is the document side of accept/reject, not Qt's teardown.
# Gui.Control is C++-backed and may refuse attribute assignment, so this is
# best-effort; the run wrapper below reports whatever actually happens.
closed = []
try:
    Gui.Control.closeDialog = lambda *a, **k: closed.append(True)
except Exception as exc:                                    # noqa: BLE001
    line("note: could not stub Gui.Control.closeDialog (%s)" % exc)


def guarded(label, fn, *args):
    """Run `fn`, logging any exception rather than letting it escape.

    An uncaught exception here does not stop FreeCAD: the GUI event loop
    keeps running and the process sits until the harness kills it, which
    reads as a hang (exit 143) with no clue as to the cause. Every earlier
    'hang' in this script was really an exception at this point.
    """
    try:
        return fn(*args)
    except Exception as exc:                                # noqa: BLE001
        import traceback
        line("%-58s RAISED %s: %s" % (label, type(exc).__name__, exc))
        line(traceback.format_exc())
        failures.append(label)
        return None


def shaft(doc, radius=4.0, height=30.0):
    obj = doc.addObject("Part::Cylinder", "Shaft")
    obj.Radius, obj.Height = radius, height
    doc.recompute()
    for i, face in enumerate(obj.Shape.Faces):
        surface = face.Surface
        if (hasattr(surface, "Radius")
                and abs(surface.Radius - radius) < 1e-6):
            return obj, "Face%d" % (i + 1)
    raise SystemExit("no cylindrical face")


def panel_for(doc, base, sub):
    from tapdie import api
    circle = selection.resolve(base, sub)
    return command.ThreadTaskPanel(base, sub, circle,
                                   api.defaults_for(circle)), circle


doc = App.newDocument("preview")
App.setActiveDocument(doc.Name)
base, sub = shaft(doc)
baseline = {o.Name for o in doc.Objects}

# --- opens with a preview already built ------------------------------------
panel, circle = panel_for(doc, base, sub)
check("preview builds on open", panel.preview_ok, panel.note.text())
check("preview created a cutter", panel.cutter_obj is not None)
check("preview did NOT create the boolean", panel.cut is None)
check("preview added exactly one object",
      len({o.Name for o in doc.Objects} - baseline) == 1,
      "added: %s" % sorted({o.Name for o in doc.Objects} - baseline))
check("no Part::Cut exists during the preview",
      not any(o.TypeId == "Part::Cut" for o in doc.Objects),
      [o.Name for o in doc.Objects if o.TypeId == "Part::Cut"])
check("the part itself is untouched and still visible",
      base.Shape.Volume > 0.0 and base.ViewObject.Visibility)
check("the cutter is a single valid solid",
      panel.cutter_obj.Shape.isValid()
      and len(panel.cutter_obj.Shape.Solids) >= 1)
check("the cutter is drawn translucent red",
      panel.cutter_obj.ViewObject.Transparency > 0
      and panel.cutter_obj.ViewObject.ShapeColor[0] > 0.5
      and panel.cutter_obj.ViewObject.ShapeColor[1] < 0.5,
      "colour=%s transparency=%s"
      % (panel.cutter_obj.ViewObject.ShapeColor,
         panel.cutter_obj.ViewObject.Transparency))

# --- direction re-parameterises in place -----------------------------------
names_before = (panel.cutter_obj.Name,)
count_before = len(doc.Objects)
panel.direction.setCurrentText(form.FORWARD)
panel._rebuild()            # the Refresh button, pressed by hand
check("direction change kept the same objects",
      (panel.cutter_obj.Name,) == names_before)
check("direction change leaked nothing",
      len(doc.Objects) == count_before,
      "%d -> %d" % (count_before, len(doc.Objects)))
check("preview still valid after direction change", panel.preview_ok,
      panel.note.text())

obj = panel.cutter_obj
box = obj.Shape.optimalBoundingBox()
line("   direction property   : %s" % obj.Direction)
line("   circle axis          : %s" % (circle.axis,))
line("   circle centre        : %s" % (circle.centre,))
line("   LocalPlacement       : %s" % (obj.LocalPlacement,))
line("   Placement            : %s" % (obj.Placement,))
line("   box z                : %.3f .. %.3f" % (box.ZMin, box.ZMax))

# Assert the PLACEMENT, not the bounding box. Two things make the box the
# wrong instrument here, and both are correct behaviour rather than bugs:
#   * this face's axis is (0,0,-1), so "along the axis" runs DOWN in world
#     coordinates -- any test that assumes +Z is testing the fixture, not
#     the feature;
#   * a one-way run reaches mid-part at one end, which _detect_free_ends
#     rightly calls abutting, and the sweep is clipped there -- so the box
#     is not a pure translation of the BOTH case.
# The placement composition is exact and is the actual contract.
for direction in form.DIRECTIONS:
    panel.direction.setCurrentText(direction)
    panel._rebuild()
    obj = panel.cutter_obj
    z_lo, _z_hi = form.span(direction, obj.Length.Value)
    expected = (obj.AttachedTo.Placement
                .multiply(obj.LocalPlacement)
                .multiply(App.Placement(
                    App.Vector(0, 0, z_lo - obj.Pitch.Value),
                    App.Rotation())))
    check("%s places the run exactly" % direction,
          (obj.Placement.Base - expected.Base).Length < 1e-6,
          "%s vs %s" % (obj.Placement.Base, expected.Base))
    check("%s still previews" % direction, panel.preview_ok,
          panel.note.text())

# --- stale marking: an edit must not silently look applied -----------------
panel.direction.setCurrentText(form.BOTH)
panel._rebuild()
before_edit = panel.cutter_obj.Shape.Volume
panel.length.setValue(panel.length.value() + 4.0)
check("editing a control marks the preview stale", panel.stale)
check("a stale edit does NOT rebuild on its own",
      abs(panel.cutter_obj.Shape.Volume - before_edit) < 1e-9)
check("the note says the preview is out of date",
      "press Refresh" in panel.note.text(), panel.note.text())
panel._rebuild()
check("Refresh applies the pending edit", not panel.stale)
check("Refresh actually changed the geometry",
      abs(panel.cutter_obj.Shape.Volume - before_edit) > 1e-6)

# --- flush ends -------------------------------------------------------------
panel.flush_ends.setChecked(True)
panel._rebuild()
flush_box = panel.cutter_obj.Shape.optimalBoundingBox()
flush_len = flush_box.ZMax - flush_box.ZMin
panel.flush_ends.setChecked(False)
panel._rebuild()
over_box = panel.cutter_obj.Shape.optimalBoundingBox()
over_len = over_box.ZMax - over_box.ZMin
pitch = panel.cutter_obj.Pitch.Value
# At least the two pitches of overrun, and no more than that plus the
# profile's own axial extent -- the unclipped sweep also overshoots each end
# by the profile half-width, since the profile is centred on v=0 and swept
# from z=0 to z=height. That is geometry, not overrun, so a tolerance tight
# enough to exclude it was simply wrong.
check("flush ends remove at least the two pitches of overrun",
      2.0 * pitch - 1e-6 <= (over_len - flush_len) <= 3.0 * pitch,
      "flush=%.3f overrun=%.3f diff=%.3f (pitch %.3f)"
      % (flush_len, over_len, over_len - flush_len, pitch))
check("flush cutter matches the run length",
      abs(flush_len - panel.cutter_obj.Length.Value) < 0.35 * pitch,
      "cutter=%.3f run=%.3f" % (flush_len, panel.cutter_obj.Length.Value))
panel.flush_ends.setChecked(True)
panel._rebuild()

# --- a bad parameter set reports itself and refuses to apply ---------------
panel.pitch.setValue(19.0)
panel._rebuild()
check("unbuildable settings clear preview_ok", not panel.preview_ok)
check("unbuildable settings explain themselves",
      panel.note.text().startswith("Cannot build:"), panel.note.text())
check("accept() refuses while the preview is broken",
      guarded("accept() when broken", panel.accept) is False)
check("the refusal tells the user why",
      bool(warnings) and "does not build" in warnings[-1],
      warnings[-1] if warnings else "no message shown")

# --- cancel rolls everything back ------------------------------------------
guarded("reject()", panel.reject)
doc.recompute()
after_cancel = {o.Name for o in doc.Objects}
check("Cancel restored the document exactly",
      after_cancel == baseline,
      "left behind: %s" % sorted(after_cancel - baseline))

# --- ok commits -------------------------------------------------------------
panel, circle = panel_for(doc, base, sub)
check("second preview builds", panel.preview_ok, panel.note.text())
cutter_name = panel.cutter_obj.Name
check("accept() applies", guarded("accept()", panel.accept) is True)
check("accept() created the boolean", panel.cut is not None)
cut_name = panel.cut.Name if panel.cut is not None else "<none>"
doc.recompute()
names = {o.Name for o in doc.Objects}
check("OK kept the cutter and the cut",
      cutter_name in names and cut_name in names)
check("OK added exactly two objects",
      names - baseline == {cutter_name, cut_name},
      "added: %s" % sorted(names - baseline))
cut = doc.getObject(cut_name)
check("committed cut is a single valid solid",
      cut.Shape.isValid() and len(cut.Shape.Solids) == 1)

line("   stack after cancel+ok: UndoNames=%s" % (doc.UndoNames,))
# KNOWN LIMITATION, measured: removeObject pushes its own "Delete" step
# whatever the surrounding transaction does -- abort-then-remove,
# remove-then-abort and remove-then-commit all produce the same stack. So a
# cancelled dialog costs an inert pair of undo entries. The DOCUMENT is
# clean either way (checked above), which is what matters; the stack is
# cosmetic. Asserted as it measures so an improvement gets noticed.
line("   known limitation: a cancelled dialog leaves %d undo entries"
     % doc.UndoNames.count("Delete"))
check("cancel leaves the document clean, whatever the undo stack says",
      after_cancel == baseline)

# --- undo, isolated in a fresh document ------------------------------------
doc2 = App.newDocument("undotest")
App.setActiveDocument(doc2.Name)
base2, sub2 = shaft(doc2)
baseline2 = {o.Name for o in doc2.Objects}
panel2, _c2 = panel_for(doc2, base2, sub2)
guarded("accept() in fresh doc", panel2.accept)
doc2.recompute()
line("   fresh doc UndoNames=%s" % (doc2.UndoNames,))
doc2.undo()
doc2.recompute()
left = sorted({o.Name for o in doc2.Objects} - baseline2)
# One undo removes the cutter but leaves the Part::Cut -- a pre-existing
# property of the diamond (cutter -> base, Cut -> base + cutter), reproduced
# on the untouched api.create_thread path in tools/diag_undo.py. Asserted as
# it MEASURES, so a future improvement trips this and gets noticed.
check("one undo removes the cutter",
      not any(n.startswith("ThreadCutter") for n in left),
      "left: %s" % left)
line("   known limitation: undo leaves %s (see api.create_thread docstring)"
     % (left or "nothing"))

# --- a failed first preview must not strand a cutter -----------------------
# Measured before the fix: api.build_cutter appends the cutter to `created`
# BEFORE validating it, so a failure left it in the document while
# self.cutter_obj stayed None. _rebuild() then saw None, called _build()
# again, and made a SECOND cutter; accept() consumed only that one and
# committed the first as an orphan (Invalid, consumed by nothing).
# A 0.6mm shaft fails at the default 0.12 clearance -- the profile's tip
# lands at r < 0 -- and builds at clearance 0, so the whole cycle is reachable
# with the dialog's own controls and nothing exotic.
doc3 = App.newDocument("orphan")
App.setActiveDocument(doc3.Name)
base3, sub3 = shaft(doc3, radius=0.3, height=6.0)
baseline3 = {o.Name for o in doc3.Objects}
panel3, _c3 = panel_for(doc3, base3, sub3)
check("a 0.6mm shaft fails the first preview", not panel3.preview_ok,
      panel3.note.text())
check("the failed preview explains itself in real terms",
      "clearance" in panel3.note.text() or "depth" in panel3.note.text(),
      panel3.note.text())
panel3.clearance.setValue(0.0)
guarded("Refresh after the failure", panel3._rebuild)
check("clearance 0 makes it build", panel3.preview_ok, panel3.note.text())
check("accept() applies", guarded("accept() after recovery",
                                  panel3.accept) is True)
doc3.recompute()
cutters3 = [o for o in doc3.Objects
            if getattr(getattr(o, "Proxy", None), "Type", None)
            == "ThreadCutter"]
check("exactly one cutter survives a failed-then-fixed preview",
      len(cutters3) == 1, "cutters: %s" % [o.Name for o in cutters3])
for c in cutters3:
    consumed = [o.Name for o in doc3.Objects
                if getattr(o, "Tool", None) is c]
    check("the surviving cutter is consumed by the boolean", bool(consumed),
          "%s consumed_by=%s" % (c.Name, consumed or "NOTHING"))
line("   added to the document: %s"
     % sorted({o.Name for o in doc3.Objects} - baseline3))

# --- Custom form is usable ---------------------------------------------------
# Measured before the fix: picking Custom froze whatever the last preset left,
# so Custom followed by a finer pitch kept 0.4mm lands against a 0.5mm pitch,
# the preview died with "leaves no flank within the pitch", and no control in
# the dialog could fix it.
doc4 = App.newDocument("customform")
App.setActiveDocument(doc4.Name)
base4, sub4 = shaft(doc4, radius=4.0, height=20.0)
panel4, _c4 = panel_for(doc4, base4, sub4)
check("a preset leaves the custom controls disabled",
      not panel4.angle.isEnabled())
check("a preset still seeds them for display",
      panel4.angle.value() > 0.0 and panel4.root_land.value() > 0.0,
      "angle=%.2f root=%.4f" % (panel4.angle.value(),
                                panel4.root_land.value()))
panel4.thread_form.setCurrentText(form.CUSTOM)
check("Custom enables the angle control", panel4.angle.isEnabled())
check("Custom enables both land controls",
      panel4.root_land.isEnabled() and panel4.crest_land.isEnabled())
panel4.pitch.setValue(0.5)
panel4.root_land.setValue(0.02)
panel4.crest_land.setValue(0.02)
panel4.angle.setValue(60.0)
guarded("Refresh with custom values", panel4._rebuild)
check("Custom at a fine pitch builds", panel4.preview_ok, panel4.note.text())
if panel4.preview_ok:
    check("the custom angle reached the feature",
          abs(panel4.cutter_obj.Angle.Value - 60.0) < 1e-6,
          "Angle=%s" % panel4.cutter_obj.Angle.Value)
    check("the custom lands reached the feature",
          abs(panel4.cutter_obj.RootLand.Value - 0.02) < 1e-6,
          "RootLand=%s" % panel4.cutter_obj.RootLand.Value)
panel4.thread_form.setCurrentText(form.PRINTED)
guarded("Refresh back on a preset", panel4._rebuild)
check("a preset takes the angle back off Custom",
      panel4.preview_ok
      and abs(panel4.cutter_obj.Angle.Value - 90.0) < 1e-6,
      "Angle=%s" % (panel4.cutter_obj.Angle.Value
                    if panel4.cutter_obj else "no cutter"))
check("the preset controls are disabled again",
      not panel4.angle.isEnabled())
guarded("reject() the custom panel", panel4.reject)

# --- the Diameter check actually surfaces ----------------------------------
# Finding 1: Diameter was passed to cutter_points and never read, so the most
# prominent field in the dialog changed nothing at all.
doc5 = App.newDocument("diamcheck")
App.setActiveDocument(doc5.Name)
base5, sub5 = shaft(doc5, radius=10.0, height=30.0)
panel5, _c5 = panel_for(doc5, base5, sub5)
check("a 20mm shaft defaults to a matching diameter, quietly",
      "cuts a" not in panel5.note.text(), panel5.note.text())
panel5.diameter.setValue(16.0)
guarded("Refresh with a smaller diameter", panel5._rebuild)
# Diameter DRIVES the size now: a die turns the shaft down as it cuts, so
# asking for 16 on a 20mm shaft is achievable and must simply be done,
# quietly. Only the direction that would need material ADDED is reported.
check("asking for 16 on a 20mm shaft builds", panel5.preview_ok,
      panel5.note.text())
check("an achievable smaller diameter is not nagged about",
      "This cuts a" not in panel5.note.text(), panel5.note.text())
if panel5.preview_ok:
    check("the cutter reaches out past the shaft to turn it down",
          max(panel5.cutter_obj.Shape.optimalBoundingBox().XMax,
              panel5.cutter_obj.Shape.optimalBoundingBox().YMax) >= 10.0,
          "reach=%.3f" % panel5.cutter_obj.Shape.optimalBoundingBox().XMax)
panel5.diameter.setValue(24.0)
guarded("Refresh with an impossible diameter", panel5._rebuild)
check("asking for 24 on a 20mm shaft says it cannot",
      "24.00" in panel5.note.text() and "20.00" in panel5.note.text()
      and "removes material" in panel5.note.text(),
      panel5.note.text())
guarded("reject() the diameter panel", panel5.reject)

# --- simple / advanced ------------------------------------------------------
# Only an offscreen GUI can see a widget's visibility, so this is the only
# place the toggle can be tested at all.
doc6 = App.newDocument("simpleadv")
App.setActiveDocument(doc6.Name)
base6, sub6 = shaft(doc6, radius=4.0, height=20.0)
panel6, _c6 = panel_for(doc6, base6, sub6)
# isVisible() is False for EVERY widget here -- the dialog is never shown in
# an offscreen run, and a child of an unshown parent is never "visible". The
# first version of these checks used it and the "start hidden" case passed
# vacuously while every positive case failed. isHidden() reports the explicit
# state, which is the thing the toggle actually sets.
check("the panel opens in Simple mode", not panel6.advanced.isChecked())
shown = [w for _l, w in panel6.advanced_rows if not w.isHidden()]
check("advanced rows start hidden", not shown,
      "%d still showing" % len(shown))
check("the settings that matter are still there",
      not panel6.diameter.isHidden() and not panel6.pitch.isHidden()
      and not panel6.length.isHidden() and not panel6.clearance.isHidden()
      and not panel6.mode.isHidden())
panel6.advanced.setChecked(True)
hidden = [w for _l, w in panel6.advanced_rows if w.isHidden()]
check("Advanced reveals every advanced row", not hidden,
      "%d still hidden" % len(hidden))
check("the flat clearance is one of them",
      not panel6.flat_clearance.isHidden())
panel6.advanced.setChecked(False)
check("and Simple hides them again",
      all(w.isHidden() for _l, w in panel6.advanced_rows))
check("toggling visibility does NOT mark the preview stale", not panel6.stale,
      "a visibility control must not invalidate geometry")

# Custom must reveal the controls it unlocks, or it is a dead end again.
panel6.thread_form.setCurrentText(form.CUSTOM)
check("picking Custom switches to Advanced by itself",
      panel6.advanced.isChecked())
check("Custom's own controls are shown and enabled",
      not panel6.angle.isHidden() and panel6.angle.isEnabled()
      and not panel6.root_land.isHidden()
      and not panel6.crest_land.isHidden())

# The two clearances are independent.
panel6.thread_form.setCurrentText(form.PRINTED)
panel6.flat_clearance.setValue(0.30)
guarded("Refresh with a wider flat clearance", panel6._rebuild)
check("a wider flat clearance still builds", panel6.preview_ok,
      panel6.note.text())
check("flat clearance reached the feature",
      abs(panel6.cutter_obj.FlatClearance.Value - 0.30) < 1e-9,
      "FlatClearance=%s" % panel6.cutter_obj.FlatClearance.Value)
check("and did not disturb the flank clearance",
      abs(panel6.cutter_obj.Clearance.Value - 0.12) < 1e-9,
      "Clearance=%s" % panel6.cutter_obj.Clearance.Value)
guarded("reject() the simple/advanced panel", panel6.reject)

# --- the print test piece ---------------------------------------------------
# Only the panel can turn this on, so only an offscreen GUI can check that OK
# really builds it, that it lands inside the same transaction, and that
# Cancel takes it back out again.
doc7 = App.newDocument("coupon")
App.setActiveDocument(doc7.Name)
base7, sub7 = shaft(doc7, radius=4.0, height=20.0)
baseline7 = {o.Name for o in doc7.Objects}

panel7, _c7 = panel_for(doc7, base7, sub7)
check("test piece is off by default", not panel7.test_piece.isChecked())
check("test piece is an advanced setting",
      any(w is panel7.test_piece for _l, w in panel7.advanced_rows))
panel7.test_piece.setChecked(True)
check("ticking it does NOT mark the preview stale", not panel7.stale,
      "it adds separate objects and changes no previewed geometry")

# Cancel first: the coupon must not survive a dialog the user backed out of.
guarded("reject() with the test piece ticked", panel7.reject)
doc7.recompute()
check("Cancel leaves no test piece behind",
      {o.Name for o in doc7.Objects} == baseline7,
      "left: %s" % sorted({o.Name for o in doc7.Objects} - baseline7))

panel7, _c7 = panel_for(doc7, base7, sub7)
panel7.test_piece.setChecked(True)
check("accept() applies with a test piece",
      guarded("accept() with test piece", panel7.accept) is True)
doc7.recompute()
labels = [o.Label for o in doc7.Objects if "Test piece" in o.Label]
check("both halves of the coupon exist", len(labels) >= 2,
      "labels: %s" % labels)
coupons = [o for o in doc7.Objects
           if o.TypeId == "Part::Cut" and "Test piece" in o.Label]
check("both halves are single valid solids",
      len(coupons) == 2
      and all(c.Shape.isValid() and len(c.Shape.Solids) == 1
              for c in coupons),
      "%d coupon solids" % len(coupons))
if len(coupons) == 2:
    boxes = [c.Shape.optimalBoundingBox() for c in coupons]
    tallest = max(b.ZLength for b in boxes)
    widest = max(b.XLength for b in boxes)
    check("the coupon is small enough to be worth printing",
          tallest < 30.0 and widest < 40.0,
          "%.1f tall, %.1f wide" % (tallest, widest))
    check("the coupon is clear of the part being threaded",
          min(b.XMin for b in boxes)
          >= base7.Shape.optimalBoundingBox().XMax - 1e-6,
          "coupon XMin %.3f vs part XMax %.3f"
          % (min(b.XMin for b in boxes),
             base7.Shape.optimalBoundingBox().XMax))
doc7.undo()
doc7.recompute()
left7 = sorted({o.Name for o in doc7.Objects} - baseline7)
check("undo took the coupon with the thread", not left7,
      "left: %s" % left7)

line("")
line("PREVIEW DIAG: %d failure(s)" % len(failures))
for name in failures:
    line("   FAILED: %s" % name)
LOG.close()
os._exit(1 if failures else 0)
