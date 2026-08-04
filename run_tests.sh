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
    run_pure 'test_packaging.py'
    ;;
  fc)
    # Piping into grep would hand back grep's exit status, not freecadcmd's,
    # and this is /bin/sh with no pipefail.  Capture output, keep the status.
    out="$ROOT/.fc-test-output"
    # flatpak run does not forward signals into the sandbox, so freecadcmd
    # processes may outlive the script on interrupt.  At least clean up our
    # output file.
    trap 'rm -f "$out"' EXIT INT TERM
    set +e
    $FC "$ROOT/tests/run_fc.py" > "$out" 2>&1
    status=$?
    set -e
    grep -vE "$NOISE" "$out" || true
    exit "$status"
    ;;
  diag)
    # freecadcmd never runs InitGui.py and has no FreeCADGui, so the task
    # panel -- the only part that owns Qt widgets, an undo transaction and
    # the enabled/disabled state of a control -- is invisible to `fc`. An
    # offscreen GUI is the only thing that sees it, and it has caught defects
    # nothing else could: a stale preview, a stranded cutter, and a set of
    # controls that never enabled.
    #
    # Same output-capture dance as `fc`: /bin/sh has no pipefail, so piping
    # into grep would hand back grep's status rather than FreeCAD's.
    out="$ROOT/.diag-test-output"
    trap 'rm -f "$out"' EXIT INT TERM
    set +e
    flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD \
        "$ROOT/tools/diag_preview.py" > "$out" 2>&1
    status=$?
    set -e
    cat "$ROOT/tools/diag_preview.log" 2>/dev/null || true
    # `[ ... ] && cmd` would be an AND-list whose own failure trips set -e
    # and exits 1 on the SUCCESS path. Use a plain if.
    if [ "$status" -ne 0 ]; then
        grep -vE "$NOISE" "$out" || true
    fi
    exit "$status"
    ;;
  all)
    "$0" pure && "$0" fc && "$0" diag
    ;;
esac
