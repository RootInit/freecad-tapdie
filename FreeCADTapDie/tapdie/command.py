"""Gui command and task panel.  The only module allowed to import FreeCADGui."""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui

# Deliberately NOT `from . import api, form, selection` at module scope.
# That chain pulls in api -> feature -> cutter, which does `import Part` and
# `import Sketcher` at import time -- and those are not reliably importable
# while InitGui.py itself is still running at FreeCAD startup. When that
# import fails partway through, Python leaves the `tapdie` package in
# sys.modules (so it LOOKS imported) but never finishes running this
# module's body, so `Gui.addCommand` at the bottom never executes and the
# command silently never registers -- no traceback, no Report view message,
# nothing. Importing these three lazily, inside each method that actually
# needs them, defers that cost past startup, by which point Part/Sketcher
# are available.

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "resources", "icons")


class ThreadTaskPanel(object):
    """Parameter dialog with a live preview of the material to be removed.

    The preview shows the CUTTER -- translucent red, over the part left
    intact -- and not the result of the boolean. The cutter solid is exactly
    the material the thread would take out, so it says the same thing, and it
    avoids consuming the part for something the user has not committed to
    yet: FreeCAD hides a Part::Cut's Base as soon as the Cut exists, so
    building the boolean up front made the part vanish the instant the dialog
    opened. This is also how FreeCAD's own Part tools preview.

    The cutter is the real object, re-parameterised in place as the controls
    change, so there is no separate preview geometry that could disagree with
    the result. The boolean happens once, on OK.
    """

    def __init__(self, base, sub_name, circle, defaults):
        from . import form

        self.base, self.sub_name = base, sub_name
        self.circle, self.defaults = circle, defaults
        # Capture the document ONCE, from the object being threaded.
        # Re-reading App.ActiveDocument at teardown is not safe: it can be
        # None, or a different document, by the time the user clicks Cancel
        # -- and then reject() raises AttributeError before it reaches the
        # cleanup, stranding the preview's cutter and Part::Cut in the tree
        # with the user's part swallowed by the boolean. Measured exactly
        # that in an offscreen GUI run.
        self.doc = base.Document
        self.cutter_obj = None
        self.cut = None
        self.created = []
        self.preview_ok = False
        self.transaction_open = False

        self.form = QtGui.QWidget()
        self.form.setWindowTitle("Tap / Die")
        layout = QtGui.QFormLayout(self.form)
        # Rows that only show in Advanced. QFormLayout.setRowVisible is Qt
        # 6.4+, so the label is built by hand and hidden with its field
        # rather than relying on it.
        self.advanced_rows = []

        def row(text, widget, advanced=False):
            label = QtGui.QLabel(text)
            layout.addRow(label, widget)
            if advanced:
                self.advanced_rows.append((label, widget))
            return widget

        self.mode = QtGui.QComboBox()
        self.mode.addItems([form.INTERNAL, form.EXTERNAL])
        self.mode.setCurrentText(defaults["Mode"])
        row("Mode", self.mode)

        self.thread_form = QtGui.QComboBox()
        self.thread_form.addItems(list(form.FORMS))
        row("Form", self.thread_form)

        # Angle and the two lands are preset-driven, so they are shown but
        # DISABLED unless Form is Custom -- mirroring the lock feature.py
        # puts on the properties themselves. Without them Custom was a dead
        # end: it froze whatever the last preset happened to leave, so
        # picking Custom and then a finer pitch kept lands wider than the
        # whole pitch, cutter_points refused ("leaves no flank within the
        # pitch"), and nothing in the dialog could recover it.
        self.angle = QtGui.QDoubleSpinBox()
        self.angle.setRange(10.5, 169.5)
        self.angle.setSingleStep(5.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        self.angle.setToolTip(
            "Included angle. 90 puts every flank at exactly the 45 degree "
            "overhang limit, which is the FDM optimum; ISO's 60 gives a 60 "
            "degree overhang and droops when printed axis-vertical.")
        row("Angle", self.angle, advanced=True)

        self.root_land = QtGui.QDoubleSpinBox()
        self.root_land.setRange(0.0005, 100.0)
        self.root_land.setDecimals(4)
        self.root_land.setSingleStep(0.005)
        self.root_land.setToolTip(
            "Flat at the bottom of the groove (the thread's root). Keeps "
            "the MATING part's crest printable.")
        row("Root land", self.root_land, advanced=True)

        self.crest_land = QtGui.QDoubleSpinBox()
        self.crest_land.setRange(0.0005, 100.0)
        self.crest_land.setDecimals(4)
        self.crest_land.setSingleStep(0.005)
        self.crest_land.setToolTip(
            "Flat left on the surface between grooves (the crest). Keeps "
            "THIS part's crest printable. Not the same job as the root "
            "land, so do not assume they should be equal.")
        row("Crest land", self.crest_land, advanced=True)

        self.diameter = QtGui.QDoubleSpinBox()
        self.diameter.setRange(0.1, 1000.0)
        self.diameter.setSingleStep(0.5)
        self.diameter.setDecimals(3)
        self.diameter.setValue(defaults["Diameter"])
        row("Diameter", self.diameter)

        self.pitch = QtGui.QDoubleSpinBox()
        self.pitch.setRange(0.05, 50.0)
        self.pitch.setSingleStep(0.25)
        self.pitch.setDecimals(3)
        self.pitch.setValue(defaults["Pitch"])
        row("Pitch", self.pitch)

        self.length = QtGui.QDoubleSpinBox()
        self.length.setRange(0.05, 2000.0)
        self.length.setDecimals(3)
        self.length.setValue(defaults["Length"])
        row("Length", self.length)

        self.direction = QtGui.QComboBox()
        self.direction.addItems(list(form.DIRECTIONS))
        self.direction.setCurrentText(defaults.get("Direction", form.BOTH))
        self.direction.setToolTip(
            "Which way the run travels from the circle you selected.\n"
            "'Both ways' straddles it -- right for a cylindrical face, "
            "wrong for an edge at the end of a rod, where half the cutter "
            "lands in open air.")
        row("Direction", self.direction)

        self.clearance = QtGui.QDoubleSpinBox()
        self.clearance.setRange(0.0, 5.0)
        self.clearance.setDecimals(3)
        self.clearance.setSingleStep(0.01)
        self.clearance.setValue(0.12)
        self.clearance.setToolTip(
            "Fit, per part. A mated pair ends up twice this apart measured "
            "normal to the FLANKS, and wider still at the flats -- by "
            "1/sin(angle/2), so 2.83x the clearance at 90 degrees.\n"
            "One setting because it can only be one: both profiles are the "
            "same V displaced radially, and one displacement fixes both "
            "gaps together.")
        row("Clearance", self.clearance)

        # Exposed because it can make a selection unbuildable and there was
        # no way to correct it: for a bore the overrun runs INWARD, so the
        # fixed 1.0mm default reached through the axis of anything under
        # r=1.0 and the preview simply refused. defaults_for now scales it
        # to the bore as well.
        self.overrun = QtGui.QDoubleSpinBox()
        self.overrun.setRange(0.01, 100.0)
        self.overrun.setDecimals(3)
        self.overrun.setSingleStep(0.1)
        self.overrun.setValue(defaults.get("Overrun", 1.0))
        self.overrun.setToolTip(
            "How far the cutter's parallel section reaches past the surface "
            "it is cutting.\nFor a bore this runs towards the axis, so it "
            "must stay under the bore radius.")
        row("Overrun", self.overrun, advanced=True)

        self.flush_ends = QtGui.QCheckBox()
        self.flush_ends.setChecked(True)
        self.flush_ends.setToolTip(
            "Face the cutter off flat where the run ends, instead of "
            "letting it overrun a pitch past them.\n"
            "An end that butts against adjacent material is always faced "
            "off, regardless of this.")
        row("Flush ends", self.flush_ends, advanced=True)

        self.start_angle = QtGui.QDoubleSpinBox()
        self.start_angle.setRange(-360.0, 360.0)
        self.start_angle.setDecimals(2)
        self.start_angle.setSingleStep(15.0)
        self.start_angle.setSuffix(" deg")
        self.start_angle.setWrapping(True)
        self.start_angle.setValue(0.0)
        self.start_angle.setToolTip(
            "Where the thread starts, around the axis. Use it to line a "
            "thread up with a flat, a hole or another thread.\n"
            "An internal thread is already clocked half a pitch round from "
            "an external one, so a nut and bolt cut with the same settings "
            "mate as they stand -- this is your adjustment on top of that.")
        row("Start angle", self.start_angle, advanced=True)

        self.left_handed = QtGui.QCheckBox()
        row("Left handed", self.left_handed, advanced=True)

        self.add_material = QtGui.QCheckBox()
        self.add_material.setChecked(bool(defaults.get("AddMaterial", True)))
        self.add_material.setToolTip(
            "Fuse a tube of material on first when -- and only when -- the "
            "diameter you asked for cannot be cut from the blank:\n"
            "a sleeve to make an external thread LARGER than its shaft, a "
            "liner to make an internal one SMALLER than its bore.\n"
            "Off, those two cases fall back to the blank and say so.")
        row("Add material if needed", self.add_material, advanced=True)

        # SIMPLE BY DEFAULT. Mode, Form, Diameter, Pitch, Length, Direction
        # and Clearance are enough to cut a thread; everything else is either
        # preset-driven or a detail most users never touch, and thirteen rows
        # of it buried the seven that matter. Purely a visibility control --
        # it changes no parameter, so it must not mark the preview stale.
        self.advanced = QtGui.QCheckBox("Show advanced settings")
        self.advanced.setToolTip(
            "Angle and lands, overrun, start angle, flush ends, "
            "handedness, and whether material may be added.")
        self.advanced.toggled.connect(self._sync_advanced)
        layout.addRow(self.advanced)

        self.refresh_button = QtGui.QPushButton("Refresh preview")
        self.refresh_button.clicked.connect(self._rebuild)
        layout.addRow(self.refresh_button)

        self.note = QtGui.QLabel("")
        self.note.setWordWrap(True)
        layout.addRow(self.note)

        # Editing a control marks the preview STALE rather than rebuilding
        # it. A helical sweep takes the better part of a second, so
        # rebuilding per edit made changing three fields cost three waits --
        # set everything you want, then press Refresh once.
        self.stale = False
        for widget in (self.mode, self.thread_form, self.direction):
            widget.currentTextChanged.connect(self._touch)
        for widget in (self.diameter, self.pitch, self.length, self.clearance,
                       self.overrun, self.angle, self.root_land,
                       self.crest_land, self.start_angle):
            widget.valueChanged.connect(self._touch)
        for widget in (self.left_handed, self.flush_ends, self.add_material):
            widget.toggled.connect(self._touch)

        self._sync_advanced()
        self._sync_form_controls()
        self._build()

    def _sync_advanced(self):
        """Show or hide the advanced rows."""
        show = self.advanced.isChecked()
        for label, widget in self.advanced_rows:
            label.setVisible(show)
            widget.setVisible(show)

    def _sync_form_controls(self):
        """Enable Angle and the lands for Custom only, seeding from the preset.

        Seeding is the point: an unseeded Custom is exactly how the dead end
        happened. Leaving a coarse preset's 0.4mm lands in place against a
        0.5mm pitch leaves no flank within the pitch at all, cutter_points
        rejects it, and before these controls existed there was nothing the
        user could do about it.
        """
        from . import form, presets

        custom = self.thread_form.currentText() == form.CUSTOM
        if custom and not self.advanced.isChecked():
            # Custom unlocks Angle and the lands, which are advanced rows --
            # leaving them hidden would recreate the dead end this control
            # was added to fix.
            self.advanced.setChecked(True)      # fires _sync_advanced
        if not custom:
            defaults = presets.form_defaults(
                self.thread_form.currentText(), self.pitch.value(),
                self.mode.currentText())
            # Block signals: these setValue calls are bookkeeping, not user
            # edits, and _touch is what calls this method.
            for widget, value in ((self.angle, defaults["angle"]),
                                  (self.root_land, defaults["root_land"]),
                                  (self.crest_land, defaults["crest_land"])):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        for widget in (self.angle, self.root_land, self.crest_land):
            widget.setEnabled(custom)

    # ---- preview -------------------------------------------------------

    def overrides(self):
        from . import form

        values = {
            "Mode": self.mode.currentText(),
            "ThreadForm": self.thread_form.currentText(),
            "Diameter": self.diameter.value(),
            "Pitch": self.pitch.value(),
            "Length": self.length.value(),
            "Direction": self.direction.currentText(),
            "Clearance": self.clearance.value(),
            "AddMaterial": self.add_material.isChecked(),
            "Overrun": self.overrun.value(),
            "StartAngle": self.start_angle.value(),
            "FlushEnds": self.flush_ends.isChecked(),
            "LeftHanded": self.left_handed.isChecked(),
        }
        # Only when Custom. On a preset these three are computed by
        # feature._apply_preset from Form/Pitch/Mode, and sending them would
        # just fight it -- api.apply_params sets the structural keys first
        # precisely so a genuine override lands last and survives.
        if self.thread_form.currentText() == form.CUSTOM:
            values["Angle"] = self.angle.value()
            values["RootLand"] = self.root_land.value()
            values["CrestLand"] = self.crest_land.value()
        return values

    def _errors(self):
        """The checked failure modes, as a tuple for `except`.

        Deliberately NOT `Exception`: these four are what the api contract
        promises (a bad selection, a profile that cannot sweep, a cutter or
        boolean that would not build, or an out-of-range property value).
        Anything else -- a typo'd override key raising AttributeError, say --
        is a programming error and must surface as a traceback rather than be
        swallowed into a friendly message.
        """
        from . import api, form, selection

        return (api.ThreadError, form.ProfileError, selection.SelectionError,
                ValueError)

    def _build(self):
        """Create the preview CUTTER inside an undo transaction.

        No boolean here -- see the class docstring.
        """
        from . import api

        doc = self.doc
        # CLEAR THE WRECKAGE OF ANY PREVIOUS ATTEMPT FIRST.
        #
        # api.build_cutter appends the cutter to `created` BEFORE validating
        # it, so a failed build leaves that object in the document while
        # self.cutter_obj stays None. _rebuild() then routes back here and
        # would build a SECOND cutter; accept() consumes only that one and
        # commits the first as an orphan. Measured through the real panel
        # offscreen: an Invalid ThreadCutter, consumed by nothing, left in
        # the tree for good beside a working ThreadCutter001 -- reached by
        # nothing more exotic than "the first preview failed, I corrected
        # it, I pressed OK".
        if self.created:
            api.discard(doc, *reversed(self.created))
            self.created = []
        # _build can run more than once for one dialog, and a second
        # openTransaction closes the first, stranding its undo entry.
        if not self.transaction_open:
            doc.openTransaction("Thread")
            self.transaction_open = True
        try:
            self.cutter_obj = api.build_cutter(
                doc, self.base, self.sub_name, self.overrides(), self.created)
            self.preview_ok = True
        except self._errors() as exc:
            self.preview_ok = False
            self._say(exc)
        else:
            self._say(None)

    def _touch(self):
        """Mark the preview out of date without rebuilding it."""
        # Before the stale flag: switching Form is what enables or disables
        # the Custom controls, and switching Pitch or Mode is what reseeds
        # them. Calling this only from __init__ left them permanently
        # disabled -- caught by tools/diag_preview.py, which is the only
        # thing that can see a widget's enabled state.
        self._sync_form_controls()
        self.stale = True
        self._say(None)

    def _rebuild(self):
        """Re-parameterise the existing preview, or build it if it is gone."""
        from . import api

        self.stale = False
        if self.cutter_obj is None:
            self._build()
            return
        try:
            # cut is None during the preview: only the cutter exists yet.
            api.update_thread(self.cutter_obj, self.cut, self.overrides())
            self.preview_ok = True
        except self._errors() as exc:
            self.preview_ok = False
            self._say(exc)
        else:
            self._say(None)

    def _say(self, exc):
        """Advisory text, or the reason the preview is not showing."""
        from . import form

        if exc is not None:
            self.note.setText("Cannot build: %s" % exc)
            self.note.setStyleSheet("color: #c0392b;")
            return
        if self.stale:
            # Never leave a changed setting looking applied. The red solid in
            # the viewport is still the OLD one until Refresh is pressed.
            self.note.setText(
                "Settings changed -- press Refresh preview to see them. "
                "OK refreshes first.")
            self.note.setStyleSheet("color: #b9770e;")
            return
        self.note.setStyleSheet("")
        # The Diameter check, ahead of the form advice: being told the thread
        # will come out a different SIZE than asked for matters more than
        # being told ISO droops. Diameter drives no geometry -- the surface
        # does -- so without this the field was inert.
        if self.cutter_obj is not None and self.preview_ok:
            from . import api

            mismatch = api.diameter_note(self.cutter_obj)
            if mismatch is not None:
                self.note.setText(mismatch)
                self.note.setStyleSheet("color: #b9770e;")
                return
            from . import feature as feature_mod

            fill = feature_mod.fill_needed(self.cutter_obj)
            if fill > 0.0:
                surface = "shaft" if self.mode.currentText() == form.EXTERNAL \
                    else "bore"
                self.note.setText(
                    "OK will add %.2fmm of material around the %s first -- "
                    "cutting alone cannot reach %.2fmm here."
                    % (fill, surface, self.diameter.value()))
                self.note.setStyleSheet("color: #1a6b9a;")
                return
        if self.thread_form.currentText() == form.ISO:
            self.note.setText(
                "ISO 60 deg gives a 60 deg overhang on every flank. Printed "
                "upright this droops without support.")
        elif self.circle.mode is None:
            self.note.setText(
                "Could not tell a bore from a shaft here -- check Mode.")
        else:
            self.note.setText("")

    # ---- dialog --------------------------------------------------------

    def accept(self):
        # An un-refreshed edit must land before OK does, or the committed
        # geometry would silently be whatever was last previewed rather than
        # what the dialog now reads.
        if self.stale:
            self._rebuild()
        if not self.preview_ok:
            QtGui.QMessageBox.warning(
                self.form, "Tap / Die",
                "The thread does not build with these settings, so there is "
                "nothing to apply.\n\n%s" % self.note.text())
            return False

        # The boolean happens HERE, not during the preview. It can still
        # fail on geometry the cutter itself was happy with -- a helical
        # Part::Cut is known to return a closed solid that is nevertheless
        # invalid -- so roll just the Cut back and keep the dialog open
        # rather than committing a broken result.
        from . import api
        # Everything added from here is rolled back together on failure, so
        # remember where the cutter's own objects ended. Popping a single
        # trailing object was enough when the Cut was the only thing this
        # step could create; adding material makes it two more.
        mark = len(self.created)
        try:
            # Material first, and only if the requested diameter cannot be
            # reached by cutting -- add_material returns `base` untouched in
            # the ordinary case. The panel used to call apply_cut directly
            # and so skipped this entirely: the note promised a sleeve and
            # OK quietly cut a clamped thread instead.
            stock = api.add_material(self.doc, self.base, self.cutter_obj,
                                     self.created)
            self.cut = api.apply_cut(self.doc, stock, self.cutter_obj,
                                     self.created)
        except self._errors() as exc:
            if self.cut is None:
                api.discard(self.doc, *reversed(self.created[mark:]))
                del self.created[mark:]
            self._say(exc)
            QtGui.QMessageBox.warning(
                self.form, "Tap / Die",
                "The cutter built, but the boolean did not.\n\n%s" % exc)
            return False

        self.doc.commitTransaction()
        self.transaction_open = False
        Gui.Control.closeDialog()
        return True

    def reject(self):
        doc = self.doc
        if self.transaction_open:
            # Remove the objects, then COMMIT -- do not abort.
            #
            # abortTransaction cannot be relied on to undo the creation:
            # measured on this build (tools/diag_undo.py), once a recompute
            # has run inside the transaction it leaves both objects in the
            # tree. A plain Part::FeaturePython plus a Part::Cut aborts
            # perfectly cleanly, so the trigger is the DIAMOND this builds --
            # the cutter links to the base via AttachedTo and the Cut
            # consumes both. Clearing those links first was tried and changed
            # nothing.
            #
            # Given that, the removal has to be explicit, and of the three
            # orderings this is the only one that is both clean and coherent:
            #   remove, then abort  -- the abort reverts the removals too and
            #       resurrects both objects (a stranded ThreadCutter001).
            #   abort, then remove  -- document clean, but the transaction is
            #       already closed, so the removals stand alone.
            #   remove, then commit -- the transaction's net effect is
            #       nothing, created and removed in one step, so undoing it
            #       is a no-op.
            #
            # All three leave the same undo stack: removeObject pushes its
            # own "Delete" step regardless of the surrounding transaction, so
            # a cancelled dialog costs an inert pair of entries either way.
            # The DOCUMENT is clean, which is what matters.
            from . import api
            api.discard(doc, *reversed(self.created))
            doc.commitTransaction()
            self.transaction_open = False
        self.created = []
        self.cutter_obj = self.cut = None
        Gui.Control.closeDialog()
        return True


class ThreadCommand(object):
    def GetResources(self):
        return {
            "Pixmap": os.path.join(ICON_DIR, "tapdie_cutter.svg"),
            "MenuText": "Tap / Die...",
            "ToolTip": "Thread a cylinder by selecting a circular profile",
        }

    def IsActive(self):
        return App.ActiveDocument is not None and bool(Gui.Selection.getSelectionEx())

    def Activated(self):
        from . import api, selection

        picks = Gui.Selection.getSelectionEx()
        if not picks or not picks[0].SubElementNames:
            QtGui.QMessageBox.warning(
                None, "Tap / Die",
                "Select a cylindrical face or a circular edge first.")
            return
        base, sub_name = picks[0].Object, picks[0].SubElementNames[0]
        try:
            circle = selection.resolve(base, sub_name)
        except selection.SelectionError as exc:
            QtGui.QMessageBox.warning(None, "Tap / Die", str(exc))
            return
        defaults = api.defaults_for(circle)
        Gui.Control.showDialog(
            ThreadTaskPanel(base, sub_name, circle, defaults))


Gui.addCommand("TapDie_Thread", ThreadCommand())
