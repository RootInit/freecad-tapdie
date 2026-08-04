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

        self.mode = QtGui.QComboBox()
        self.mode.addItems([form.INTERNAL, form.EXTERNAL])
        self.mode.setCurrentText(defaults["Mode"])
        layout.addRow("Mode", self.mode)

        self.thread_form = QtGui.QComboBox()
        self.thread_form.addItems(list(form.FORMS))
        layout.addRow("Form", self.thread_form)

        self.diameter = QtGui.QDoubleSpinBox()
        self.diameter.setRange(0.5, 500.0)
        self.diameter.setDecimals(3)
        self.diameter.setValue(defaults["Diameter"])
        layout.addRow("Diameter", self.diameter)

        self.pitch = QtGui.QDoubleSpinBox()
        self.pitch.setRange(0.1, 20.0)
        self.pitch.setDecimals(3)
        self.pitch.setValue(defaults["Pitch"])
        layout.addRow("Pitch", self.pitch)

        self.length = QtGui.QDoubleSpinBox()
        self.length.setRange(0.5, 1000.0)
        self.length.setDecimals(3)
        self.length.setValue(defaults["Length"])
        layout.addRow("Length", self.length)

        self.direction = QtGui.QComboBox()
        self.direction.addItems(list(form.DIRECTIONS))
        self.direction.setCurrentText(defaults.get("Direction", form.BOTH))
        self.direction.setToolTip(
            "Which way the run travels from the circle you selected.\n"
            "'Both ways' straddles it -- right for a cylindrical face, "
            "wrong for an edge at the end of a rod, where half the cutter "
            "lands in open air.")
        layout.addRow("Direction", self.direction)

        self.clearance = QtGui.QDoubleSpinBox()
        self.clearance.setRange(0.0, 2.0)
        self.clearance.setDecimals(3)
        self.clearance.setSingleStep(0.01)
        self.clearance.setValue(0.12)
        layout.addRow("Clearance", self.clearance)

        self.flush_ends = QtGui.QCheckBox()
        self.flush_ends.setChecked(True)
        self.flush_ends.setToolTip(
            "Face the cutter off flat where the run ends, instead of "
            "letting it overrun a pitch past them.\n"
            "An end that butts against adjacent material is always faced "
            "off, regardless of this.")
        layout.addRow("Flush ends", self.flush_ends)

        self.left_handed = QtGui.QCheckBox()
        layout.addRow("Left handed", self.left_handed)

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
        for widget in (self.diameter, self.pitch, self.length, self.clearance):
            widget.valueChanged.connect(self._touch)
        for widget in (self.left_handed, self.flush_ends):
            widget.toggled.connect(self._touch)

        self._build()

    # ---- preview -------------------------------------------------------

    def overrides(self):
        from . import form

        return {
            "Mode": self.mode.currentText(),
            "ThreadForm": self.thread_form.currentText(),
            "Diameter": self.diameter.value(),
            "Pitch": self.pitch.value(),
            "Length": self.length.value(),
            "Direction": self.direction.currentText(),
            "Clearance": self.clearance.value(),
            "FlushEnds": self.flush_ends.isChecked(),
            "LeftHanded": self.left_handed.isChecked(),
        }

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
        try:
            self.cut = api.apply_cut(self.doc, self.base, self.cutter_obj,
                                     self.created)
        except self._errors() as exc:
            if self.cut is None and self.created \
                    and self.created[-1] is not self.cutter_obj:
                api.discard(self.doc, self.created.pop())
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
