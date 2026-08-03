"""Register the tap/die command and inject it into the Part workbench.

addWorkbenchManipulator is the supported way to add commands to a workbench
someone else owns; the bundled BIM workbench uses the same mechanism.
"""

import FreeCADGui as Gui


class TapDieManipulator:
    def modifyMenuBar(self):
        # Part_Boolean is a SUBMENU trigger, not a top-level Part menu item --
        # confirmed by dumping the live Part menu -- so anchoring on it put
        # the insert nowhere visible even once loading itself was fixed.
        # Part_Fillet is a genuine top-level item (confirmed the same way,
        # alongside Part_Extrude/Part_Revolve/Part_Mirror/Part_Section/etc.),
        # and sits in the modelling-operations run where a tap/die belongs.
        # `after` matches BIM's own working descriptor shape exactly.
        return [{"insert": "TapDie_Thread", "menuItem": "Part_Fillet",
                 "after": ""}]

    def modifyToolBars(self):
        # Two things are unverified here, not one:
        #   1. The toolbar DISPLAY NAME "Part_Booleans" -- found only by
        #      static inspection (`grep -aoE 'Part_[A-Za-z]+s\\b' PartGui.so`
        #      turns it up as a string distinct from the singular
        #      "Part_Boolean" command in Shortcuts.cfg, matching the
        #      plural-group/singular-command pattern of Part_Datums,
        #      Part_CrossSections), never by launching the GUI. Keep it as
        #      the best evidence-based guess, not a confirmed id.
        #   2. The action verb. The only working modifyToolBars in this
        #      build -- BIM's nativeifc/ifc_status.py -- uses "append", not
        #      "insert" ({"append": "IFC_Save", "toolBar": "File"}), and its
        #      "File" is a human-readable toolbar display name, not a
        #      command-group id like "Part_Booleans". Match its verb here;
        #      the toolbar NAME is still the open question.
        #
        # If the button does not appear under the Part workbench, delete this
        # method; the menu entry alone is a supported fallback.
        return [{"append": "TapDie_Thread", "toolBar": "Part_Booleans"}]


def _register():
    try:
        from tapdie import command      # noqa: F401  (registers the command)
    except Exception:
        # A failure here used to be SILENT: `tapdie` was left in
        # sys.modules (Python does that for a package whose submodule import
        # raised partway through) while command.py's `Gui.addCommand` at
        # module end never ran, so "TapDie_Thread" in Gui.listCommands() was
        # False with no traceback anywhere -- diagnosing that cost several
        # round trips. Never let that happen invisibly again: print the full
        # traceback to the Report view so a startup failure is loud.
        import traceback
        import FreeCAD as App
        App.Console.PrintError(
            "TapDie: failed to register its command; the Part menu entry "
            "will be missing.\n" + traceback.format_exc())
        return
    if not getattr(Gui, "_tapdie_manipulator", None):
        Gui._tapdie_manipulator = TapDieManipulator()
        Gui.addWorkbenchManipulator(Gui._tapdie_manipulator)


_register()
