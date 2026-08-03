"""Register the tap/die command and inject it into the Part workbench.

addWorkbenchManipulator is the supported way to add commands to a workbench
someone else owns; the bundled BIM workbench uses the same mechanism.
"""

import FreeCADGui as Gui


class TapDieManipulator:
    def modifyMenuBar(self):
        return [{"insert": "TapDie_Thread", "menuItem": "Part_Boolean"}]

    def modifyToolBars(self):
        # "Part_Booleans" is UNVERIFIED as a live toolbar in this build -- it
        # was not confirmed by launching the GUI, only by static inspection:
        # `grep -aoE 'Part_[A-Za-z]+s\b' PartGui.so` turns up "Part_Booleans"
        # and "Part_Primitives" as isolated strings distinct from the actual
        # command names (the dropdown command is the singular "Part_Boolean",
        # per FreeCAD's Shortcuts.cfg), which is the naming pattern FreeCAD
        # uses for a C++ ToolBarItem group -- e.g. Part_Datums,
        # Part_CrossSections follow the same plural-group/singular-command
        # split. That is circumstantial, not a confirmed toolbar id.
        #
        # modifyToolBars itself IS a working, precedented mechanism, contrary
        # to what an earlier pass through this file assumed: BIM's own
        # nativeifc/ifc_status.py defines an IFC_WBManipulator with a real
        # modifyToolBars (inserting into the "File" toolbar), it is just a
        # different manipulator than the menu-only one in BIM/InitGui.py.
        #
        # If the button does not appear under the Part workbench, delete this
        # method; the menu entry alone is a supported fallback.
        return [{"insert": "TapDie_Thread", "toolBar": "Part_Booleans"}]


def _register():
    from tapdie import command      # noqa: F401  (registers the command)
    if not getattr(Gui, "_tapdie_manipulator", None):
        Gui._tapdie_manipulator = TapDieManipulator()
        Gui.addWorkbenchManipulator(Gui._tapdie_manipulator)


_register()
