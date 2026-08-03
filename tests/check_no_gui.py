"""Confirms no non-Gui tapdie module pulls in FreeCADGui.

An `assert` here would print nothing useful and, worse, freecadcmd exits 0
even when a script raises an uncaught exception -- only SystemExit changes
the process exit code.  So this has to check explicitly and raise
SystemExit(1) itself, matching tests/run_fc.py, or a caller gating on exit
status would never see a failure.
"""

import sys
sys.path.insert(0, "/home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie")
from tapdie import api, cutter, feature, form, measure, presets, selection

if "FreeCADGui" in sys.modules:
    # flush=True: freecadcmd does not flush stdout before SystemExit unwinds
    # the interpreter, so an unflushed print here is silently lost -- the
    # same buffering trap tests/run_fc.py already works around.
    print("no-Gui check: FAILED -- a non-GUI module imported FreeCADGui",
          flush=True)
    raise SystemExit(1)

print("no-Gui check: ok", flush=True)
