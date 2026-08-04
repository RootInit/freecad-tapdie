"""Register the tap/die command and inject it into the Part workbench.

addWorkbenchManipulator is the supported way to add commands to a workbench
someone else owns; the bundled BIM workbench uses the same mechanism.

FreeCAD does not import this file -- it exec()s it with distinct globals and
locals dicts.  Top-level statements therefore bind into *locals*, while the
body of any function or method defined here resolves its free names in
*globals*, where those bindings do not exist.  A top-level `def _register()`
referring to a top-level `class TapDieManipulator` (or to the module-level
`Gui`) raises NameError at startup, and the message goes only to stdout --
"During initialization the error ... occurred in ...InitGui.py" -- never to
the Report view, so it is invisible to anyone launching FreeCAD normally.

Hence: no module-level functions, and no method here may reference a
module-level name.  The two manipulator methods return literals only.
"""

import FreeCADGui as Gui


class TapDieManipulator:
    def modifyMenuBar(self):
        # Part_Boolean is a SUBMENU trigger, not a top-level Part menu item
        # (confirmed by dumping the live Part menu), so anchoring on it put
        # the insert nowhere visible even once loading itself was fixed.
        # Part_Fillet is a genuine top-level item, confirmed the same way
        # alongside Part_Extrude/Part_Revolve/Part_Mirror/Part_Section, and
        # sits in the modelling-operations run where a tap/die belongs.
        # `after` matches BIM's own working descriptor shape.
        return [{"insert": "TapDie_Thread", "menuItem": "Part_Fillet",
                 "after": ""}]

    def modifyToolBars(self):
        # The toolbar is addressed by its human-readable DISPLAY name, not by
        # a command-group id: dumping the live Part workbench's toolbars gives
        # 'Solids', 'Part Tools' and 'Boolean Tools'.  The earlier guess
        # "Part_Booleans", reverse-engineered from strings in PartGui.so,
        # matches nothing and silently did nothing.  'Part Tools' is the
        # modelling-operation bar (Extrude, Revolve, Fillet, Chamfer, Loft,
        # Sweep), which is where a tap/die belongs; 'Boolean Tools' holds the
        # raw set operations.  "append" matches BIM's working descriptor
        # ({"append": "IFC_Save", "toolBar": "File"}).
        return [{"append": "TapDie_Thread", "toolBar": "Part Tools"}]


try:
    from tapdie import command      # noqa: F401  (registers the command)
except Exception:
    # A failure here used to be SILENT: `tapdie` was left in sys.modules
    # (Python does that for a package whose submodule import raised partway
    # through) while command.py's `Gui.addCommand` at module end never ran,
    # so "TapDie_Thread" in Gui.listCommands() was False with no traceback
    # anywhere.  Never let that happen invisibly again.
    import traceback

    import FreeCAD as App
    App.Console.PrintError(
        "TapDie: failed to register its command; the Part menu entry will be "
        "missing.\n" + traceback.format_exc())
else:
    if not getattr(Gui, "_tapdie_manipulator", None):
        Gui._tapdie_manipulator = TapDieManipulator()
        Gui.addWorkbenchManipulator(Gui._tapdie_manipulator)
