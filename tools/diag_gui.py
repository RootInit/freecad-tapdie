"""Startup diagnostic, run inside a real (offscreen) FreeCAD GUI session.

freecadcmd cannot answer the question that matters -- it never runs InitGui.py
and has no FreeCADGui -- so the only honest test of "does the command register
at startup" is a full GUI launch.  QT_QPA_PLATFORM=offscreen makes that
possible without a window.
"""

import os
import sys

import FreeCAD as App
import FreeCADGui as Gui

# stdout from a GUI launch is buffered and interleaved with Qt noise; a file
# is the only reliable channel back out of this process.
LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "diag_gui.log"), "w")


def line(msg):
    LOG.write("%s\n" % msg)
    LOG.flush()


line("tapdie in sys.modules      : %s" % ("tapdie" in sys.modules))
line("tapdie.command in modules  : %s" % ("tapdie.command" in sys.modules))
line("command registered         : %s"
     % ("TapDie_Thread" in Gui.listCommands()))
line("manipulator attr present   : %s"
     % bool(getattr(Gui, "_tapdie_manipulator", None)))

paths = [p for p in sys.path if "TapDie" in p]
line("sys.path entries w/ TapDie : %s" % paths)

# If it did not register, import it by hand and show exactly why.
if "TapDie_Thread" not in Gui.listCommands():
    try:
        from tapdie import command  # noqa: F401
        line("manual import OK; now registered: %s"
             % ("TapDie_Thread" in Gui.listCommands()))
    except Exception:
        import traceback
        line("manual import FAILED:\n" + traceback.format_exc())

# What the Part workbench actually offers, so the menu anchor can be checked
# against reality rather than against a guess.
try:
    Gui.activateWorkbench("PartWorkbench")
    wb = Gui.getWorkbench("PartWorkbench")
    line("Part workbench activated")
    mw = Gui.getMainWindow()
    for menu in mw.menuBar().actions():
        if menu.text().replace("&", "") != "Part":
            continue
        names = []
        for act in menu.menu().actions():
            names.append("%s[%s]" % (act.text().replace("&", ""),
                                     act.objectName() or "-"))
        line("Part menu items: %s" % names)
    from PySide import QtWidgets
    for t in mw.findChildren(QtWidgets.QToolBar):
        acts = [a.objectName() or a.text().replace("&", "")
                for a in t.actions()]
        line("toolbar %-28s visible=%-5s %s"
             % (repr(t.objectName() or t.windowTitle()), t.isVisible(), acts))
except Exception:
    import traceback
    line("workbench probe failed:\n" + traceback.format_exc())

line("DONE")
LOG.close()
os._exit(0)
