#!/bin/sh
# Test runner.  "pure" needs no FreeCAD; "fc" runs inside the flatpak.
#
# A harness that cannot fail is worse than no harness, so both halves take
# care to propagate a real failure while tolerating "no tests written yet".
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
FC="flatpak run --command=freecadcmd org.freecad.FreeCAD"
NOISE='^FreeCAD 1|^\(C\)|Importing|%\)|free and open'

# unittest discover exits 5 when a pattern matches no file, which is the
# normal state early in the build.  Tolerate ONLY 5 -- a real test failure is
# exit 1 and must still propagate.
run_pure() {
    set +e
    PYTHONPATH="$ROOT/FreeCADTapDie:$ROOT" python3 -m unittest discover \
        -s "$ROOT/tests" -p "$1" -v
    status=$?
    set -e
    [ "$status" -eq 5 ] && return 0
    return "$status"
}

case "${1:-all}" in
  pure)
    run_pure 'test_form.py'
    run_pure 'test_presets.py'
    ;;
  fc)
    # Piping into grep would hand back grep's exit status, not freecadcmd's,
    # and this is /bin/sh with no pipefail.  Capture output, keep the status.
    out="$ROOT/.fc-test-output"
    set +e
    $FC "$ROOT/tests/run_fc.py" > "$out" 2>&1
    status=$?
    set -e
    grep -vE "$NOISE" "$out" || true
    rm -f "$out"
    exit "$status"
    ;;
  all)
    "$0" pure && "$0" fc
    ;;
esac
