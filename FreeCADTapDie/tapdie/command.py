"""Gui command and task panel.  The only module allowed to import FreeCADGui."""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui

from . import api, form, selection

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "resources", "icons")


class ThreadTaskPanel(object):
    """Minimal parameter dialog: everything else is edited on the object."""

    def __init__(self, base, sub_name, circle, defaults):
        self.base, self.sub_name = base, sub_name
        self.circle, self.defaults = circle, defaults

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

        self.clearance = QtGui.QDoubleSpinBox()
        self.clearance.setRange(0.0, 2.0)
        self.clearance.setDecimals(3)
        self.clearance.setSingleStep(0.01)
        self.clearance.setValue(0.12)
        layout.addRow("Clearance", self.clearance)

        self.left_handed = QtGui.QCheckBox()
        layout.addRow("Left handed", self.left_handed)

        self.note = QtGui.QLabel("")
        self.note.setWordWrap(True)
        layout.addRow(self.note)

        self.thread_form.currentTextChanged.connect(self._warn)
        self._warn()

    def _warn(self):
        if self.thread_form.currentText() == form.ISO:
            self.note.setText(
                "ISO 60 deg gives a 60 deg overhang on every flank. Printed "
                "upright this droops without support.")
        elif self.circle.mode is None:
            self.note.setText(
                "Could not tell a bore from a shaft here -- check Mode.")
        else:
            self.note.setText("")

    def accept(self):
        overrides = {
            "Mode": self.mode.currentText(),
            "ThreadForm": self.thread_form.currentText(),
            "Diameter": self.diameter.value(),
            "Pitch": self.pitch.value(),
            "Length": self.length.value(),
            "Clearance": self.clearance.value(),
            "LeftHanded": self.left_handed.isChecked(),
        }
        try:
            api.create_thread(App.ActiveDocument, self.base, self.sub_name,
                              overrides)
        except Exception as exc:
            QtGui.QMessageBox.warning(self.form, "Tap / Die", str(exc))
            return False
        Gui.Control.closeDialog()
        return True

    def reject(self):
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
