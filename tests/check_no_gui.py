import sys
sys.path.insert(0, "/home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie")
from tapdie import api, cutter, feature, form, measure, presets, selection
assert "FreeCADGui" not in sys.modules, "a non-GUI module imported FreeCADGui"
print("no-Gui check: ok")
