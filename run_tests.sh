#!/bin/sh
# Test runner.  "pure" needs no FreeCAD; "fc" runs inside the flatpak.
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
FC="flatpak run --command=freecadcmd org.freecad.FreeCAD"
NOISE='^FreeCAD 1|^\(C\)|Importing|%\)|free and open'

case "${1:-all}" in
  pure)
    PYTHONPATH="$ROOT/FreeCADTapDie:$ROOT" python3 -m unittest discover \
        -s "$ROOT/tests" -p 'test_form.py' -v || true
    PYTHONPATH="$ROOT/FreeCADTapDie:$ROOT" python3 -m unittest discover \
        -s "$ROOT/tests" -p 'test_presets.py' -v || true
    ;;
  fc)
    $FC "$ROOT/tests/run_fc.py" 2>&1 | grep -vE "$NOISE"
    ;;
  all)
    "$0" pure && "$0" fc
    ;;
esac
