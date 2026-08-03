# FreeCAD Tap/Die Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FreeCAD Part-workbench command that threads any cylinder — internal (tap) or external (die) — by selecting a circular profile, generating a helical cutter solid, and cutting it with a native `Part::Cut`.

**Architecture:** The plugin's only geometric job is producing one correct cutter solid. That solid is built by an `AdditiveHelix` as the base feature of a `PartDesign::Body` inside a **hidden scratch document**, whose `Shape` is copied out before the document is closed. A `ThreadCutter` FeaturePython object owns the parameters and that shape; FreeCAD's own `Part::Cut` performs the boolean. All logic lives below a `FreeCADGui`-free API so it is testable headlessly.

**Tech Stack:** FreeCAD 1.1.1 (flatpak), Python 3, `unittest` (stdlib only — no pytest dependency).

## Global Constraints

- FreeCAD is a **flatpak**. There is no system `freecad` and no importable `FreeCAD` module. Run everything as: `flatpak run --command=freecadcmd org.freecad.FreeCAD <script.py>`
- **The flatpak sandbox cannot read `/tmp`.** Every script, test and output must live under `/home/alexander`. A file under `/tmp` fails with an unhelpful `Exception while processing file`.
- Filter banner noise from FreeCAD output with: `| grep -vE '^FreeCAD 1|^\(C\)|Importing|%\)'`
- Repo root: `/home/alexander/Documents/CAD/freecad_tapdie`
- Addon package dir: `<repo>/FreeCADTapDie` — symlinked into `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/`
- **Never use `Shape.slice()`** — it returns zero wires at the plane through the axis. Use `Shape.section()` against an explicit `Part.Face`.
- **Never use `Shape.BoundBox`** for measuring a trimmed solid — use `optimalBoundingBox()`.
- **A valid solid is not a correct solid.** `isValid()` and `len(Solids) == 1` are preconditions only; every generated cutter must additionally have its flank angle and land widths measured.
- Modules under `tapdie/` must **never** `import FreeCADGui` except `command.py`.
- **Rebuild latency is already measured** — 0.09 s (15 turns), 0.19 s (4 turns),
  0.23 s (40 turns) for a full hidden-document cutter build. No caching layer is
  needed; do not add one speculatively.
- Commit message trailer, on every commit:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw
  ```

## File Structure

| File | Responsibility |
|---|---|
| `FreeCADTapDie/tapdie/form.py` | Cutter profile mathematics. Pure Python, no FreeCAD import. |
| `FreeCADTapDie/tapdie/presets.py` | ISO coarse-pitch table and diameter lookup. Pure Python. |
| `FreeCADTapDie/tapdie/measure.py` | Section-based profile measurement of a built solid. |
| `FreeCADTapDie/tapdie/cutter.py` | Profile points → `Part.Shape`, via a hidden-document Body. |
| `FreeCADTapDie/tapdie/feature.py` | `ThreadCutter` FeaturePython proxy + ViewProvider. |
| `FreeCADTapDie/tapdie/selection.py` | Selection → centre, axis, radius, internal/external. |
| `FreeCADTapDie/tapdie/api.py` | `create_thread()` orchestration. No Gui import. |
| `FreeCADTapDie/tapdie/command.py` | Task panel + Gui command. The only Gui-aware module. |
| `FreeCADTapDie/InitGui.py` | Command registration + Part workbench injection. |
| `tests/` | `test_form.py`, `test_presets.py` (pure) and `test_cutter.py`, `test_selection.py`, `test_integration.py` (FreeCAD). |

---

### Task 1: Repo scaffolding and the pure-Python test harness

**Files:**
- Create: `FreeCADTapDie/tapdie/__init__.py`
- Create: `tests/__init__.py`
- Create: `run_tests.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: `./run_tests.sh pure` runs stdlib-unittest tests with the addon package importable; `./run_tests.sh fc` runs FreeCAD tests under `freecadcmd`.

- [ ] **Step 1: Create the package directories and empty init files**

```bash
cd /home/alexander/Documents/CAD/freecad_tapdie
mkdir -p FreeCADTapDie/tapdie FreeCADTapDie/resources/icons tests
touch FreeCADTapDie/tapdie/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write the test runner**

Create `run_tests.sh`:

```bash
#!/bin/sh
# Test runner.  "pure" needs no FreeCAD; "fc" runs inside the flatpak.
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
FC="flatpak run --command=freecadcmd org.freecad.FreeCAD"
NOISE='^FreeCAD 1|^\(C\)|Importing|%\)|free and open'

case "${1:-all}" in
  pure)
    PYTHONPATH="$ROOT/FreeCADTapDie:$ROOT" python3 -m unittest discover \
        -s "$ROOT/tests" -p 'test_form.py' -v
    PYTHONPATH="$ROOT/FreeCADTapDie:$ROOT" python3 -m unittest discover \
        -s "$ROOT/tests" -p 'test_presets.py' -v
    ;;
  fc)
    $FC "$ROOT/tests/run_fc.py" 2>&1 | grep -vE "$NOISE"
    ;;
  all)
    "$0" pure && "$0" fc
    ;;
esac
```

```bash
chmod +x run_tests.sh
```

- [ ] **Step 3: Write the FreeCAD-side test entry point**

Create `tests/run_fc.py`:

```python
"""Entry point for the FreeCAD-dependent tests.

freecadcmd executes a script, not a test runner, so unittest is driven by
hand.  Exits non-zero on failure so run_tests.sh propagates the result.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "FreeCADTapDie"))
sys.path.insert(0, ROOT)

MODULES = ["tests.test_cutter", "tests.test_selection", "tests.test_integration"]

suite = unittest.TestSuite()
loader = unittest.TestLoader()
for name in MODULES:
    try:
        suite.addTests(loader.loadTestsFromName(name))
    except (ImportError, AttributeError):
        print("  (skipping %s -- not written yet)" % name)

result = unittest.TextTestRunner(verbosity=2).run(suite)
print("FC TESTS: %d run, %d failures, %d errors"
      % (result.testsRun, len(result.failures), len(result.errors)))
if not result.wasSuccessful():
    raise SystemExit(1)
```

- [ ] **Step 4: Verify the harness runs and reports zero tests**

Run: `./run_tests.sh fc`
Expected: three "(skipping ...)" lines and `FC TESTS: 0 run, 0 failures, 0 errors`

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie tests run_tests.sh
git commit -m "chore: scaffold addon package and test harness

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 2: `form.py` — cutter profile mathematics

**Files:**
- Create: `FreeCADTapDie/tapdie/form.py`
- Test: `tests/test_form.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Constants `INTERNAL = "Internal"`, `EXTERNAL = "External"`, `PRINTED = "Printed 90"`, `ISO = "ISO metric 60"`, `CUSTOM = "Custom"`
  - `depth(form, pitch, angle, mode) -> float`
  - `cutter_points(mode, form, diameter, pitch, angle, land, clearance, surface_radius, overrun) -> list[(radius, axial)]` — six tuples
  - `ProfileError(Exception)`

**Geometry contract.** All radii are measured from the axis; `axial` is the
offset along the axis from the profile centre. `tan = tan(angle/2)`,
`sec = 1/cos(angle/2)`. Offsetting a V by normal clearance `c` moves its apex
**radially** by `c * sec`, never by `c`.

```
INTERNAL (cut outward from a bore)      EXTERNAL (cut inward from an OD)
  apex   = D/2 + c*sec                    apex   = D/2 - depth - c*sec
  tip    = apex - (land/2)/tan            tip    = apex + (land/2)/tan
  should = apex - hw/tan                  should = apex + hw/tan
  far    = min(should, r_surf) - overrun  far    = max(should, r_surf) + overrun
  requires should >= r_surface            requires should <= r_surface
```
with `hw = (pitch - land) / 2` in both cases.

- [ ] **Step 1: Write the failing test**

Create `tests/test_form.py`:

```python
import math
import unittest

from tapdie import form


class TestDepth(unittest.TestCase):
    def test_printed_v_spends_whole_pitch_on_flanks(self):
        # At 45 deg flanks the two flanks alone eat the pitch, so depth = P/2.
        d = form.depth(form.PRINTED, 3.8, 90.0, form.INTERNAL)
        self.assertAlmostEqual(d, 1.9, places=6)

    def test_printed_depth_tracks_angle(self):
        d = form.depth(form.PRINTED, 3.8, 60.0, form.INTERNAL)
        self.assertAlmostEqual(d, 3.8 / (2 * math.tan(math.radians(30))), places=6)

    def test_iso_internal_is_five_eighths_H(self):
        H = 1.25 * math.sqrt(3) / 2
        d = form.depth(form.ISO, 1.25, 60.0, form.INTERNAL)
        self.assertAlmostEqual(d, 5 * H / 8, places=6)
        self.assertAlmostEqual(d, 0.5413 * 1.25, places=3)

    def test_iso_external_is_seventeen_twentyfourths_H(self):
        H = 1.25 * math.sqrt(3) / 2
        d = form.depth(form.ISO, 1.25, 60.0, form.EXTERNAL)
        self.assertAlmostEqual(d, 17 * H / 24, places=6)


class TestCutterPoints(unittest.TestCase):
    """Reproduces the printed_threads nut cutter, which is measured and known."""

    KW = dict(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
              pitch=3.8, angle=90.0, land=0.08, clearance=0.12,
              surface_radius=8.2597, overrun=1.0)

    def points(self, **over):
        kw = dict(self.KW)
        kw.update(over)
        return form.cutter_points(
            kw["mode"], kw["form_name"], kw["diameter"], kw["pitch"],
            kw["angle"], kw["land"], kw["clearance"], kw["surface_radius"],
            kw["overrun"])

    def test_returns_six_corners(self):
        self.assertEqual(len(self.points()), 6)

    def test_tip_radius_matches_measured_geometry(self):
        # printed_threads measures the nut root land at r = 10.1297.
        self.assertAlmostEqual(self.points()[0][0], 10.1297, places=3)

    def test_tip_land_is_the_requested_width(self):
        pts = self.points()
        self.assertAlmostEqual(pts[0][1] - pts[5][1], 0.08, places=6)

    def test_parallel_section_is_pitch_minus_land(self):
        pts = self.points()
        self.assertAlmostEqual(pts[2][1] - pts[3][1], 3.8 - 0.08, places=6)

    def test_flank_is_at_the_half_angle(self):
        pts = self.points()
        tip, shoulder = pts[0], pts[1]
        dr = abs(shoulder[0] - tip[0])
        dz = abs(shoulder[1] - tip[1])
        self.assertAlmostEqual(math.degrees(math.atan2(dr, dz)), 45.0, places=4)

    def test_external_mirrors_outward(self):
        pts = self.points(mode=form.EXTERNAL, surface_radius=10.0,
                          diameter=20.0)
        self.assertLess(pts[0][0], pts[1][0])   # tip inside shoulder
        self.assertLess(pts[1][0], pts[2][0])   # shoulder inside far end

    def test_land_wider_than_half_pitch_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            self.points(land=2.0)

    def test_zero_land_is_rejected(self):
        with self.assertRaises(form.ProfileError):
            self.points(land=0.0)

    def test_shoulder_short_of_the_bore_is_rejected(self):
        # A bore far larger than the thread leaves the cutter unable to reach.
        with self.assertRaises(form.ProfileError):
            self.points(surface_radius=15.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh pure`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapdie.form'`

- [ ] **Step 3: Write the implementation**

Create `FreeCADTapDie/tapdie/form.py`:

```python
"""Cutter profile mathematics.

Pure Python -- this module must never import FreeCAD, so it stays fast to test.

The cutter is a truncated V that runs PARALLEL to the axis once past its
shoulder.  The parallel section is what lets it clear the crest without the
swept solid ever exceeding one pitch in width -- a plain triangle would have to
be exactly one pitch wide at the crest radius, which is the tangency case where
consecutive turns of the sweep touch each other.
"""

import math

INTERNAL = "Internal"
EXTERNAL = "External"

PRINTED = "Printed 90"
ISO = "ISO metric 60"
CUSTOM = "Custom"

FORMS = (PRINTED, ISO, CUSTOM)


class ProfileError(Exception):
    """The requested parameters cannot produce a sweepable cutter."""


def _tan(angle):
    return math.tan(math.radians(angle / 2.0))


def _sec(angle):
    return 1.0 / math.cos(math.radians(angle / 2.0))


def depth(form_name, pitch, angle, mode):
    """Radial depth of the thread.

    ISO is a truncated V with standard H/8 and H/4 truncations, so its depth
    is a fixed fraction of H.  The printed form is a near-sharp V, which spends
    the whole pitch on flanks -- so its depth follows directly from the angle.
    """
    if form_name == ISO:
        H = pitch * math.sqrt(3.0) / 2.0
        return 5.0 * H / 8.0 if mode == INTERNAL else 17.0 * H / 24.0
    return pitch / (2.0 * _tan(angle))


def cutter_points(mode, form_name, diameter, pitch, angle, land, clearance,
                  surface_radius, overrun):
    """Six corners of the swept cutter as (radius, axial_offset) tuples.

    Ordered tip -> shoulder -> far -> far -> shoulder -> tip, which is a simple
    closed polygon in both modes.
    """
    if land <= 0.0:
        raise ProfileError(
            "land is %.4f; a mathematically sharp crest is the tangency case "
            "where consecutive turns of the sweep touch" % land)
    if land >= pitch / 2.0:
        raise ProfileError(
            "land %.4f must stay under half the pitch (%.4f)"
            % (land, pitch / 2.0))
    if pitch <= 0.0:
        raise ProfileError("pitch must be positive")
    if not 10.0 < angle < 170.0:
        raise ProfileError("included angle %.1f is out of range" % angle)

    tan, sec = _tan(angle), _sec(angle)
    hw = (pitch - land) / 2.0
    tip_run = (land / 2.0) / tan
    flank_run = hw / tan
    d = depth(form_name, pitch, angle, mode)

    if mode == INTERNAL:
        apex = diameter / 2.0 + clearance * sec
        tip = apex - tip_run
        shoulder = apex - flank_run
        if shoulder < surface_radius:
            raise ProfileError(
                "cutter shoulder at r=%.4f cannot reach the bore at r=%.4f; "
                "increase Diameter or Pitch" % (shoulder, surface_radius))
        far = min(shoulder, surface_radius) - overrun
        if far <= 0.0:
            raise ProfileError("cutter reaches through the axis")
    else:
        apex = diameter / 2.0 - d - clearance * sec
        tip = apex + tip_run
        shoulder = apex + flank_run
        if shoulder > surface_radius:
            raise ProfileError(
                "cutter shoulder at r=%.4f overshoots the surface at r=%.4f; "
                "reduce Diameter or Pitch" % (shoulder, surface_radius))
        far = max(shoulder, surface_radius) + overrun
        if tip <= 0.0:
            raise ProfileError("thread is deeper than the shaft radius")

    half_land = land / 2.0
    return [
        (tip, half_land),
        (shoulder, hw),
        (far, hw),
        (far, -hw),
        (shoulder, -hw),
        (tip, -half_land),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./run_tests.sh pure`
Expected: PASS — 12 tests OK

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/form.py tests/test_form.py
git commit -m "feat: cutter profile mathematics

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 3: `presets.py` — ISO table and diameter lookup

**Files:**
- Create: `FreeCADTapDie/tapdie/presets.py`
- Test: `tests/test_presets.py`

**Interfaces:**
- Consumes: `tapdie.form.depth`, `tapdie.form.INTERNAL`
- Produces:
  - `ISO_COARSE` — tuple of `(nominal_diameter, pitch)` pairs
  - `nearest_for_bore(bore_diameter) -> (diameter, pitch)`
  - `nearest_for_shaft(shaft_diameter) -> (diameter, pitch)`
  - `form_defaults(form_name) -> dict` with keys `angle`, `land_fraction`

**The critical rule.** Picking the ISO entry whose *nominal* diameter is nearest
the detected bore is wrong on **every** size from M3 to M24 — a 6.8 mm hole is
0.2 mm from M7 but 1.2 mm from M8. Minimise the *reconstruction* error
`| bore - (D - 2*depth_internal(P)) |` instead.

- [ ] **Step 1: Write the failing test**

Create `tests/test_presets.py`:

```python
import unittest

from tapdie import presets


class TestBoreLookup(unittest.TestCase):
    """Standard tap-drill sizes must map to the size they are drilled for."""

    CASES = [(2.5, 3.0), (3.3, 4.0), (4.2, 5.0), (5.0, 6.0),
             (6.8, 8.0), (8.5, 10.0), (10.2, 12.0), (14.0, 16.0),
             (17.5, 20.0), (21.0, 24.0)]

    def test_tap_drill_maps_to_its_nominal_size(self):
        for bore, expected in self.CASES:
            got, _pitch = presets.nearest_for_bore(bore)
            self.assertAlmostEqual(
                got, expected, places=3,
                msg="%.1fmm bore -> M%.0f, expected M%.0f"
                    % (bore, got, expected))

    def test_the_headline_case_picks_M8_not_M7(self):
        diameter, pitch = presets.nearest_for_bore(6.8)
        self.assertAlmostEqual(diameter, 8.0, places=3)
        self.assertAlmostEqual(pitch, 1.25, places=3)

    def test_naive_nearest_nominal_would_have_picked_M7(self):
        # Guards against anyone "simplifying" the lookup back to the bug.
        naive = min(presets.ISO_COARSE, key=lambda e: abs(e[0] - 6.8))
        self.assertAlmostEqual(naive[0], 7.0, places=3)


class TestShaftLookup(unittest.TestCase):
    def test_shaft_maps_to_its_own_nominal(self):
        for shaft in (6.0, 8.0, 10.0, 20.0):
            got, _ = presets.nearest_for_shaft(shaft)
            self.assertAlmostEqual(got, shaft, places=3)

    def test_slightly_undersize_shaft_still_maps_up(self):
        got, _ = presets.nearest_for_shaft(9.94)
        self.assertAlmostEqual(got, 10.0, places=3)


class TestFormDefaults(unittest.TestCase):
    def test_printed_is_ninety_degrees(self):
        self.assertAlmostEqual(presets.form_defaults("Printed 90")["angle"],
                               90.0, places=6)

    def test_iso_is_sixty_degrees(self):
        self.assertAlmostEqual(presets.form_defaults("ISO metric 60")["angle"],
                               60.0, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh pure`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapdie.presets'`

- [ ] **Step 3: Write the implementation**

Create `FreeCADTapDie/tapdie/presets.py`:

```python
"""ISO coarse-pitch table and the diameter lookups that use it.

Pure Python -- no FreeCAD import.
"""

from . import form

# (nominal diameter mm, coarse pitch mm), ISO 261.
ISO_COARSE = (
    (3.0, 0.50), (4.0, 0.70), (5.0, 0.80), (6.0, 1.00), (7.0, 1.00),
    (8.0, 1.25), (10.0, 1.50), (12.0, 1.75), (14.0, 2.00), (16.0, 2.00),
    (18.0, 2.50), (20.0, 2.50), (22.0, 2.50), (24.0, 3.00),
)


def nearest_for_bore(bore_diameter):
    """Best (diameter, pitch) for a detected bore.

    A tap drill is deliberately larger than the theoretical minor diameter --
    it targets roughly 75% thread engagement -- so this reconstructs the minor
    diameter each table entry implies and takes the closest match.  Choosing
    the entry whose NOMINAL diameter is nearest picks the wrong, smaller size
    on every entry in the table, because the pitch spacing between adjacent
    sizes is comparable to the depth being reconstructed.

    The result is a starting guess for the user to confirm, not an exact
    relationship: residual error runs to roughly a third of a millimetre.
    """
    def error(entry):
        diameter, pitch = entry
        minor = diameter - 2.0 * form.depth(
            form.ISO, pitch, 60.0, form.INTERNAL)
        return abs(bore_diameter - minor)

    return min(ISO_COARSE, key=error)


def nearest_for_shaft(shaft_diameter):
    """Best (diameter, pitch) for a detected shaft.

    A die cuts into an existing OD, so the shaft IS the major diameter and a
    plain nearest-nominal match is correct here.
    """
    return min(ISO_COARSE, key=lambda e: abs(e[0] - shaft_diameter))


def form_defaults(form_name):
    """Angle and land fraction a preset imposes.

    `land_fraction` multiplies the pitch.  0.021 reproduces the 0.08 mm land at
    a 3.8 mm pitch that printed_threads measures and prints successfully; ISO
    uses its standard H/8 crest truncation.
    """
    if form_name == form.ISO:
        return {"angle": 60.0, "land_fraction": 0.125}
    return {"angle": 90.0, "land_fraction": 0.021}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./run_tests.sh pure`
Expected: PASS — all `test_presets` tests OK, `test_form` still OK

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/presets.py tests/test_presets.py
git commit -m "feat: ISO coarse table and reconstruction-error diameter lookup

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 4: `measure.py` and `cutter.py` — build the solid and prove it is the right shape

These ship together because neither is independently testable: the measurer
needs a swept solid to measure, and the cutter's only meaningful assertion is a
measurement.

**Files:**
- Create: `FreeCADTapDie/tapdie/measure.py`
- Create: `FreeCADTapDie/tapdie/cutter.py`
- Test: `tests/test_cutter.py`

**Interfaces:**
- Consumes: `tapdie.form.cutter_points`
- Produces:
  - `measure.cut_plane() -> Part.Face`
  - `measure.profile(shape, z_lo, z_hi, r_max=None) -> dict` with keys
    `flank_angles` (list of float degrees), `lands` (list of `(radius, width)`),
    `r_min`, `r_max`
  - `cutter.build(points, pitch, height, left_handed=False) -> Part.Shape`
  - `cutter.CutterError(Exception)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cutter.py`:

```python
import math
import unittest

import FreeCAD as App

from tapdie import cutter, form, measure


def build(mode=form.INTERNAL, form_name=form.PRINTED, diameter=20.0,
          pitch=3.8, angle=90.0, land=0.08, clearance=0.12,
          surface_radius=8.2597, height=15.2):
    pts = form.cutter_points(mode, form_name, diameter, pitch, angle, land,
                             clearance, surface_radius, 1.0)
    return cutter.build(pts, pitch, height)


class TestCutterSolid(unittest.TestCase):
    def test_produces_a_single_valid_solid(self):
        sh = build()
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)

    def test_shape_outlives_the_scratch_document(self):
        before = len(App.listDocuments())
        sh = build()
        self.assertGreater(sh.Volume, 0.0)
        self.assertEqual(len(App.listDocuments()), before,
                         "scratch document was left open")

    def test_flank_angle_is_the_requested_half_angle(self):
        # This is the check that a validity test cannot make.  MakePipeShell
        # returned valid single solids here while distorting flanks to 38-60
        # degrees, so the angle must be measured, not assumed.
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        self.assertTrue(prof["flank_angles"], "no flanks found in section")
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 45.0, places=2)

    def test_tip_land_is_the_requested_width(self):
        sh = build()
        prof = measure.profile(sh, 3.0, 12.0)
        tips = [w for r, w in prof["lands"] if abs(r - 10.1297) < 0.01]
        self.assertTrue(tips, "no tip land found; lands=%s" % prof["lands"])
        for w in tips:
            self.assertAlmostEqual(w, 0.08, places=3)

    def test_sixty_degree_form_gives_thirty_degree_flanks(self):
        sh = build(form_name=form.ISO, angle=60.0, pitch=1.25, land=0.15,
                   diameter=8.0, surface_radius=3.4, height=8.0)
        prof = measure.profile(sh, 2.0, 6.0)
        self.assertTrue(prof["flank_angles"])
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 30.0, places=2)

    def test_shallow_lead_angle_survives(self):
        # Fine pitch on a large diameter -- the case that broke MakePipeShell.
        sh = build(pitch=1.0, land=0.05, surface_radius=9.3, height=15.0)
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)
        prof = measure.profile(sh, 3.0, 12.0)
        for a in prof["flank_angles"]:
            self.assertAlmostEqual(a, 45.0, places=2)

    def test_external_mode_builds(self):
        sh = build(mode=form.EXTERNAL, surface_radius=10.0, diameter=20.0)
        self.assertTrue(sh.isValid())
        self.assertEqual(len(sh.Solids), 1)


class TestMeasureIsHonest(unittest.TestCase):
    def test_section_finds_a_known_cone_flank(self):
        """Control: a 45 degree cone must measure as 45 degrees.

        If this fails the measurement is broken, not the cutter.
        """
        import Part
        cone = Part.makeCone(10.0, 0.0, 10.0)
        prof = measure.profile(cone, 1.0, 9.0)
        self.assertTrue(prof["flank_angles"])
        self.assertAlmostEqual(prof["flank_angles"][0], 45.0, places=2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh fc`
Expected: FAIL — `(skipping tests.test_cutter -- not written yet)` becomes an import error once the file exists, reported as `ModuleNotFoundError: No module named 'tapdie.cutter'`

- [ ] **Step 3: Write `measure.py`**

Create `FreeCADTapDie/tapdie/measure.py`:

```python
"""Measure a built solid's thread profile off a plane section.

A valid solid is not a correct solid.  Every MakePipeShell variant tested
during design returned isValid() == True with exactly one solid while carrying
the wrong flank angle, so validity is a precondition and this module is the
actual guard.
"""

import math

import FreeCAD as App
import Part

AXIAL_TOL = 1e-6
MIN_RADIUS = 1.0


def cut_plane(reach=200.0):
    """A real face on y=0, big enough to pass through any plausible part.

    Shape.slice(Vector(0,1,0), 0) returns ZERO wires on solids of revolution
    here -- no error, just an empty result that reads as 'the plane missed the
    solid'.  Sectioning against an explicit face cannot fail that way.
    """
    pts = [App.Vector(-reach, 0, -reach), App.Vector(reach, 0, -reach),
           App.Vector(reach, 0, reach), App.Vector(-reach, 0, reach)]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def profile(shape, z_lo, z_hi, r_max=None):
    """Straight segments of the profile on the +x side of y=0.

    Returns flank angles measured from the axis, and cylindrical bands (lands)
    as (radius, axial width).  Only segments lying wholly inside the z window
    are considered, so partial features at the window edges cannot skew it.
    """
    flanks, lands, radii = [], [], []
    for edge in shape.section(cut_plane()).Edges:
        a = edge.Vertexes[0].Point
        b = edge.Vertexes[-1].Point
        if min(a.x, b.x) < MIN_RADIUS:
            continue
        if r_max is not None and max(a.x, b.x) > r_max:
            continue
        if not (z_lo < a.z < z_hi and z_lo < b.z < z_hi):
            continue
        radii.extend([a.x, b.x])
        dr, dz = b.x - a.x, b.z - a.z
        if abs(dr) < AXIAL_TOL:
            lands.append((round(a.x, 4), abs(dz)))
        elif abs(dz) >= AXIAL_TOL:
            flanks.append(math.degrees(math.atan2(abs(dr), abs(dz))))

    return {
        "flank_angles": flanks,
        "lands": lands,
        "r_min": min(radii) if radii else None,
        "r_max": max(radii) if radii else None,
    }
```

- [ ] **Step 4: Write `cutter.py`**

Create `FreeCADTapDie/tapdie/cutter.py`:

```python
"""Build the swept cutter solid.

The sweep is done by a PartDesign AdditiveHelix used as the BASE feature of a
Body, inside a hidden scratch document.  The Body's shape is then the swept
solid itself -- nothing to subtract, nothing to infer -- and a copy of it
survives closing the document.

PartDesign is a document object type, not a GUI workbench, so none of this
requires a GUI or an active workbench.  The obvious alternative,
Part.BRepOffsetAPI.MakePipeShell over Part.makeLongHelix, was tested across 12
configurations during design and distorted the profile in every one: flank
angles of 38-60 degrees where 45 or 30 was wanted, and radii off by up to
1.1 mm, all while reporting a valid single solid.  Do not reintroduce it.
"""

import FreeCAD as App
import Part
import Sketcher

SCRATCH = "tapdie_scratch"

XZ_PLANE = 4      # index into Body.Origin.OriginFeatures
Z_AXIS = 2


class CutterError(Exception):
    """The sweep did not produce a usable solid."""


def build(points, pitch, height, left_handed=False):
    """Sweep `points` (radius, axial) into a helical solid.

    Returns a Part.Shape detached from any document.
    """
    if len(points) < 3:
        raise CutterError("a cutter profile needs at least 3 corners")
    if pitch <= 0.0 or height <= 0.0:
        raise CutterError("pitch and height must both be positive")

    doc = App.newDocument(SCRATCH, hidden=True)
    try:
        body = doc.addObject("PartDesign::Body", "Cutter")
        sketch = doc.addObject("Sketcher::SketchObject", "Profile")
        body.addObject(sketch)
        sketch.AttachmentSupport = [(body.Origin.OriginFeatures[XZ_PLANE], "")]
        sketch.MapMode = "FlatFace"

        # A sketch attached FlatFace to XZ maps (u, v) -> global (X, 0, Z), so
        # u is a radius and v an axial position.
        n = len(points)
        for i in range(n):
            a, b = points[i], points[(i + 1) % n]
            sketch.addGeometry(
                Part.LineSegment(App.Vector(a[0], a[1], 0),
                                 App.Vector(b[0], b[1], 0)), False)
        for i in range(n):
            sketch.addConstraint(
                Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))

        helix = doc.addObject("PartDesign::AdditiveHelix", "Helix")
        body.addObject(helix)
        helix.Profile = sketch
        helix.ReferenceAxis = (body.Origin.OriginFeatures[Z_AXIS], [""])
        helix.Mode = 0                  # pitch and height
        helix.Pitch = pitch
        helix.Height = height
        helix.Angle = 0.0
        helix.LeftHanded = bool(left_handed)

        doc.recompute()

        if "Up-to-date" not in helix.State:
            raise CutterError("helix did not recompute: %s" % helix.State)

        shape = body.Shape.copy()
        if not shape.isValid():
            raise CutterError("swept cutter is not a valid solid")
        if len(shape.Solids) != 1:
            raise CutterError(
                "swept cutter has %d solids, expected 1" % len(shape.Solids))
        if shape.Volume <= 0.0:
            raise CutterError("swept cutter has no volume")
        return shape
    finally:
        App.closeDocument(doc.Name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh fc`
Expected: PASS — 8 tests OK. The control test (`test_section_finds_a_known_cone_flank`) must pass; if it fails, fix `measure.py` before trusting any other result in this task.

- [ ] **Step 6: Commit**

```bash
git add FreeCADTapDie/tapdie/measure.py FreeCADTapDie/tapdie/cutter.py tests/test_cutter.py
git commit -m "feat: helical cutter via hidden-document AdditiveHelix

Built as the base feature of a PartDesign Body in a hidden document; the
copied shape survives closing it.  MakePipeShell was rejected during design
for distorting the profile in all 12 tested configurations.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 5: `selection.py` — resolve a selection to an axis and a mode

**Files:**
- Create: `FreeCADTapDie/tapdie/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Consumes: `tapdie.form.INTERNAL`, `tapdie.form.EXTERNAL`
- Produces:
  - `Circle` namedtuple with fields `centre` (App.Vector), `axis` (App.Vector), `radius` (float), `mode` (str or None), `length` (float)
  - `resolve(obj, sub_name) -> Circle`
  - `SelectionError(Exception)`
  - `AmbiguousMode(SelectionError)` — raised when the probe cannot decide

**Detection rule.** `isInside()` must be called with `checkFace=True`; with the
default a circle lying on a flat end face reads `False/False` and gives no
signal. There are four outcomes, not two:

| inside / outside | meaning |
|---|---|
| `False` / `True` | bore → INTERNAL |
| `True` / `False` | shaft → EXTERNAL |
| `True` / `True` | counterbore step, or probe landed in bulk → ambiguous |
| `False` / `False` | epsilon exceeded the wall → retry smaller, then ambiguous |

- [ ] **Step 1: Write the failing test**

Create `tests/test_selection.py`:

```python
import unittest

import FreeCAD as App
import Part

from tapdie import form, selection


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("seltest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _add(self, shape):
        obj = self.doc.addObject("Part::Feature", "S")
        obj.Shape = shape
        self.doc.recompute()
        return obj

    def _cylindrical_face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - radius) < 1e-6:
                return "Face%d" % (i + 1)
        raise AssertionError("no cylindrical face of radius %.3f" % radius)

    def test_shaft_outer_face_is_external(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertEqual(circle.mode, form.EXTERNAL)
        self.assertAlmostEqual(circle.radius, 10.0, places=6)

    def test_bore_inner_face_is_internal(self):
        outer = Part.makeCylinder(20.0, 30.0)
        bore = Part.makeCylinder(8.0, 30.0)
        obj = self._add(outer.cut(bore))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 8.0))
        self.assertEqual(circle.mode, form.INTERNAL)
        self.assertAlmostEqual(circle.radius, 8.0, places=6)

    def test_axis_is_unit_length(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertAlmostEqual(circle.axis.Length, 1.0, places=9)

    def test_face_length_becomes_the_default_length(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        circle = selection.resolve(obj, self._cylindrical_face(obj, 10.0))
        self.assertAlmostEqual(circle.length, 30.0, places=3)

    def test_circular_edge_resolves(self):
        obj = self._add(Part.makeCylinder(10.0, 30.0))
        name = None
        for i, e in enumerate(obj.Shape.Edges):
            if hasattr(e.Curve, "Radius"):
                name = "Edge%d" % (i + 1)
                break
        self.assertIsNotNone(name)
        circle = selection.resolve(obj, name)
        self.assertAlmostEqual(circle.radius, 10.0, places=6)

    def test_planar_face_is_rejected(self):
        obj = self._add(Part.makeBox(10, 10, 10))
        with self.assertRaises(selection.SelectionError):
            selection.resolve(obj, "Face1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh fc`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapdie.selection'`

- [ ] **Step 3: Write the implementation**

Create `FreeCADTapDie/tapdie/selection.py`:

```python
"""Turn a user selection into an axis, a radius and a thread mode."""

import collections

import FreeCAD as App
import Part

from . import form

Circle = collections.namedtuple(
    "Circle", ["centre", "axis", "radius", "mode", "length"])

# Probe offsets, tried largest first, so a thin wall still gets an answer.
PROBE_FRACTIONS = (0.05, 0.01, 0.002)
MIN_PROBE = 1e-4


class SelectionError(Exception):
    """The selection is not something that can be threaded."""


class AmbiguousMode(SelectionError):
    """Internal vs external could not be determined; ask the user."""


def _from_face(face):
    surface = face.Surface
    if not isinstance(surface, Part.Cylinder):
        raise SelectionError("select a cylindrical face or a circular edge")
    bb = face.optimalBoundingBox()
    axis = App.Vector(surface.Axis)
    axis.normalize()
    length = abs(bb.ZLength * axis.z) + abs(bb.YLength * axis.y) \
        + abs(bb.XLength * axis.x)
    return App.Vector(surface.Center), axis, surface.Radius, length


def _from_edge(edge, solid):
    curve = edge.Curve
    if not isinstance(curve, Part.Circle):
        raise SelectionError("select a cylindrical face or a circular edge")
    axis = App.Vector(curve.Axis)
    axis.normalize()
    bb = solid.optimalBoundingBox()
    length = max(bb.XLength, bb.YLength, bb.ZLength)
    return App.Vector(curve.Center), axis, curve.Radius, length


def detect_mode(solid, centre, axis, radius):
    """Decide internal vs external by probing just inside and just outside.

    checkFace=True is required: with the default, a circle lying on a flat end
    face reads False/False and gives no signal at all.
    """
    ref = App.Vector(1, 0, 0)
    if abs(ref.dot(axis)) > 0.9:
        ref = App.Vector(0, 1, 0)
    radial = ref.cross(axis)
    radial.normalize()

    for fraction in PROBE_FRACTIONS:
        eps = max(radius * fraction, MIN_PROBE)
        inner = centre + radial * (radius - eps)
        outer = centre + radial * (radius + eps)
        in_solid = solid.isInside(inner, 1e-7, True)
        out_solid = solid.isInside(outer, 1e-7, True)
        if in_solid and not out_solid:
            return form.EXTERNAL
        if out_solid and not in_solid:
            return form.INTERNAL
        if in_solid and out_solid:
            # Both solid: a counterbore step, or the probe landed in bulk
            # material unrelated to this circle.  A smaller probe will not
            # help, so stop.
            raise AmbiguousMode(
                "material on both sides of the selected circle; set Mode by "
                "hand (counterbore or stepped feature?)")
    raise AmbiguousMode(
        "no material on either side of the selected circle; set Mode by hand")


def resolve(obj, sub_name):
    """Resolve (object, subelement name) to a Circle.

    `mode` is None when detection was ambiguous, so callers can fall back to
    asking rather than guessing.
    """
    shape = obj.Shape
    if sub_name.startswith("Face"):
        face = shape.getElement(sub_name)
        centre, axis, radius, length = _from_face(face)
    elif sub_name.startswith("Edge"):
        edge = shape.getElement(sub_name)
        centre, axis, radius, length = _from_edge(edge, shape)
    else:
        raise SelectionError(
            "select a cylindrical face or a circular edge, not %s" % sub_name)

    if radius <= 0.0:
        raise SelectionError("selected circle has no radius")

    try:
        mode = detect_mode(shape, centre, axis, radius)
    except AmbiguousMode:
        mode = None

    return Circle(centre=centre, axis=axis, radius=radius, mode=mode,
                  length=length)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run_tests.sh fc`
Expected: PASS — cutter tests still OK plus 6 selection tests OK

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/selection.py tests/test_selection.py
git commit -m "feat: selection resolution with four-outcome mode detection

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 6: `feature.py` — the ThreadCutter parametric object

**Files:**
- Create: `FreeCADTapDie/tapdie/feature.py`
- Test: `tests/test_integration.py` (created here, extended in Task 7)

**Interfaces:**
- Consumes: `tapdie.form`, `tapdie.cutter`, `tapdie.presets`
- Produces:
  - `ThreadCutter` proxy class
  - `make_cutter(doc, name="ThreadCutter") -> App.DocumentObject`
  - Property names, exactly: `Mode`, `ThreadForm`, `Diameter`, `Pitch`, `Angle`,
    `Land`, `Clearance`, `Length`, `SurfaceRadius`, `Overrun`, `LeftHanded`,
    `Reversed`, `AttachedTo`, `LocalPlacement`

**Naming note.** The spec calls the crest/root flat `Truncation`; this plan uses
`Land` throughout, matching the vocabulary the sibling project measures in. The
two mean the same thing — do not introduce both.

**Following the base part.** `AttachedTo` (a link) and `LocalPlacement` are how
the cutter stays with the part. Composing `AttachedTo.Placement` with
`LocalPlacement` handles **rotation as well as translation**; an expression on
`Placement.Base.x` handles neither correctly, because `circle.centre` read off
`obj.Shape` is already in global coordinates and would double-count the base's
own placement.

- [ ] **Step 1: Write the failing test**

Create `tests/test_integration.py`:

```python
import unittest

import FreeCAD as App
import Part

from tapdie import feature, form


class TestThreadCutterFeature(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("feattest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _cutter(self, **props):
        obj = feature.make_cutter(self.doc)
        obj.Mode = props.pop("Mode", form.INTERNAL)
        obj.Diameter = props.pop("Diameter", 20.0)
        obj.Pitch = props.pop("Pitch", 3.8)
        obj.Land = props.pop("Land", 0.08)
        obj.Clearance = props.pop("Clearance", 0.12)
        obj.SurfaceRadius = props.pop("SurfaceRadius", 8.2597)
        obj.Length = props.pop("Length", 15.2)
        for k, v in props.items():
            setattr(obj, k, v)
        self.doc.recompute()
        return obj

    def test_recomputes_to_a_valid_solid(self):
        obj = self._cutter()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)

    def test_editing_pitch_changes_the_shape(self):
        obj = self._cutter()
        before = obj.Shape.Volume
        obj.Pitch = 2.0
        obj.Land = 0.05
        self.doc.recompute()
        self.assertNotAlmostEqual(obj.Shape.Volume, before, places=3)

    def test_impossible_parameters_leave_the_feature_in_error(self):
        obj = self._cutter()
        obj.Land = 5.0            # wider than half the pitch
        self.doc.recompute()
        self.assertTrue("Invalid" in obj.State or "Touched" in obj.State,
                        "expected an error state, got %s" % obj.State)

    def test_reversed_runs_the_thread_the_other_way(self):
        obj = self._cutter()
        forward = obj.Shape.optimalBoundingBox()
        obj.Reversed = True
        self.doc.recompute()
        back = obj.Shape.optimalBoundingBox()
        self.assertAlmostEqual(obj.Shape.Volume, obj.Shape.Volume, places=6)
        self.assertLess(back.ZMax, forward.ZMax - 1.0)

    def test_preset_locks_the_angle(self):
        obj = self._cutter(ThreadForm=form.ISO, Pitch=1.25, Diameter=8.0,
                           SurfaceRadius=3.4, Land=0.15, Length=8.0)
        self.assertAlmostEqual(obj.Angle.Value, 60.0, places=6)
        self.assertTrue(obj.getEditorMode("Angle"))

    def test_custom_form_unlocks_the_angle(self):
        obj = self._cutter(ThreadForm=form.CUSTOM)
        self.assertEqual(obj.getEditorMode("Angle"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh fc`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapdie.feature'`

- [ ] **Step 3: Write the implementation**

Create `FreeCADTapDie/tapdie/feature.py`:

```python
"""The ThreadCutter parametric object.

Holds the parameters and produces the cutter solid.  It never performs the
boolean -- that is a native Part::Cut, so FreeCAD owns it.
"""

import FreeCAD as App

from . import cutter, form, presets

ICON = "tapdie_cutter.svg"


class ThreadCutter(object):
    """Proxy for a Part::FeaturePython carrying a helical cutter solid."""

    def __init__(self, obj):
        self.Type = "ThreadCutter"
        self.add_properties(obj)
        obj.Proxy = self

    def add_properties(self, obj):
        p = obj.addProperty
        if not hasattr(obj, "Mode"):
            p("App::PropertyEnumeration", "Mode", "Thread",
              "Internal cuts outward from a bore; external cuts inward from "
              "an OD")
            obj.Mode = [form.INTERNAL, form.EXTERNAL]
            obj.Mode = form.INTERNAL
        if not hasattr(obj, "ThreadForm"):
            p("App::PropertyEnumeration", "ThreadForm", "Thread",
              "Preset profile; Custom unlocks angle and land")
            obj.ThreadForm = list(form.FORMS)
            obj.ThreadForm = form.PRINTED
        if not hasattr(obj, "Diameter"):
            p("App::PropertyLength", "Diameter", "Thread",
              "Nominal major diameter of the thread")
            obj.Diameter = 20.0
        if not hasattr(obj, "Pitch"):
            p("App::PropertyLength", "Pitch", "Thread", "Thread pitch")
            obj.Pitch = 3.8
        if not hasattr(obj, "Angle"):
            p("App::PropertyAngle", "Angle", "Thread",
              "Included angle; overhang when printed upright is 90 - angle/2")
            obj.Angle = 90.0
        if not hasattr(obj, "Land"):
            p("App::PropertyLength", "Land", "Thread",
              "Flat left at every crest and root")
            obj.Land = 0.08
        if not hasattr(obj, "Clearance"):
            p("App::PropertyLength", "Clearance", "Fit",
              "Gap normal to the flanks")
            obj.Clearance = 0.12
        if not hasattr(obj, "Length"):
            p("App::PropertyLength", "Length", "Extent", "Threaded length")
            obj.Length = 15.2
        if not hasattr(obj, "SurfaceRadius"):
            p("App::PropertyLength", "SurfaceRadius", "Extent",
              "Radius of the cylindrical surface being threaded")
            obj.SurfaceRadius = 8.2597
        if not hasattr(obj, "Overrun"):
            p("App::PropertyLength", "Overrun", "Extent",
              "How far the cutter's parallel section runs past the surface")
            obj.Overrun = 1.0
        if not hasattr(obj, "LeftHanded"):
            p("App::PropertyBool", "LeftHanded", "Thread", "Left-hand thread")
            obj.LeftHanded = False
        if not hasattr(obj, "Reversed"):
            p("App::PropertyBool", "Reversed", "Extent",
              "Run the thread the other way along the axis from the selection")
            obj.Reversed = False
        if not hasattr(obj, "AttachedTo"):
            p("App::PropertyLink", "AttachedTo", "Base",
              "Part this cutter follows, so the thread stays with it when it "
              "moves")
        if not hasattr(obj, "LocalPlacement"):
            p("App::PropertyPlacement", "LocalPlacement", "Base",
              "Cutter frame in the base part's local coordinates")

    def onDocumentRestored(self, obj):
        self.add_properties(obj)

    def _apply_preset(self, obj):
        """Presets drive angle and land; Custom hands them back to the user."""
        locked = 1 if obj.ThreadForm != form.CUSTOM else 0
        if obj.ThreadForm != form.CUSTOM:
            defaults = presets.form_defaults(obj.ThreadForm)
            obj.Angle = defaults["angle"]
            obj.Land = defaults["land_fraction"] * obj.Pitch.Value
        obj.setEditorMode("Angle", locked)
        obj.setEditorMode("Land", locked)

    def onChanged(self, obj, prop):
        if prop in ("ThreadForm", "Pitch") and hasattr(obj, "Angle"):
            self._apply_preset(obj)

    def execute(self, obj):
        points = form.cutter_points(
            obj.Mode, obj.ThreadForm, obj.Diameter.Value, obj.Pitch.Value,
            obj.Angle.Value, obj.Land.Value, obj.Clearance.Value,
            obj.SurfaceRadius.Value, obj.Overrun.Value)

        # Overrun a whole pitch at each end: a groove that stops at the face
        # leaves a collar of plain surface for the mating crest to jam on.
        height = obj.Length.Value + 2.0 * obj.Pitch.Value
        shape = cutter.build(points, obj.Pitch.Value, height,
                             left_handed=obj.LeftHanded)
        shape.translate(App.Vector(0, 0, -obj.Pitch.Value))

        if obj.Reversed:
            # 180 deg about X is a proper rotation, so the helix keeps its
            # handedness while running the other way along the axis.
            shape.rotate(App.Vector(0, 0, 0), App.Vector(1, 0, 0), 180.0)

        obj.Shape = shape

        # Part::Cut keeps Base and Tool placements independent, so the cutter
        # has to follow the base itself.  Composing placements is correct under
        # rotation as well as translation; assigning obj.Shape resets Placement,
        # so this must come after it.
        if obj.AttachedTo is not None:
            obj.Placement = obj.AttachedTo.Placement.multiply(
                obj.LocalPlacement)


class ThreadCutterViewProvider(object):
    """Draws the cutter as a translucent red tool, not as a part."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_cutter(doc, name="ThreadCutter"):
    """Create a ThreadCutter in `doc` and return it."""
    obj = doc.addObject("Part::FeaturePython", name)
    ThreadCutter(obj)
    if App.GuiUp:
        ThreadCutterViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.9, 0.2, 0.2)
        obj.ViewObject.Transparency = 60
    return obj
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run_tests.sh fc`
Expected: PASS — 5 feature tests OK, earlier tests still OK

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/feature.py tests/test_integration.py
git commit -m "feat: ThreadCutter parametric feature

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 7: `api.py` — orchestration, placement binding, and the boolean

**Files:**
- Create: `FreeCADTapDie/tapdie/api.py`
- Modify: `tests/test_integration.py` (append the classes below)

**Interfaces:**
- Consumes: `tapdie.feature.make_cutter`, `tapdie.selection.resolve`, `tapdie.presets`
- Produces:
  - `defaults_for(circle) -> dict` with keys `Mode`, `Diameter`, `Pitch`, `Length`, `SurfaceRadius`
  - `create_thread(doc, base, sub_name, overrides=None) -> (cutter_obj, cut_obj)`
  - `ThreadError(Exception)`

**Placement binding is mandatory.** `Part::Cut` keeps `Base` and `Tool` as
independent objects with independent placements. Verified during design:
moving the base 50 mm leaves the cutter behind, and the `Cut` recomputes to the
**full uncut volume while reporting success**. The cutter's `Placement` must be
bound by expression to the base's.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_integration.py`, before the `if __name__` block:

```python
from tapdie import api


class TestCreateThread(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("apitest", hidden=True)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _bored_block(self, bore_radius=3.4, height=20.0):
        outer = Part.makeCylinder(10.0, height)
        bore = Part.makeCylinder(bore_radius, height)
        obj = self.doc.addObject("Part::Feature", "Part")
        obj.Shape = outer.cut(bore)
        self.doc.recompute()
        return obj

    def _bore_face(self, obj, radius):
        for i, f in enumerate(obj.Shape.Faces):
            if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - radius) < 1e-6:
                return "Face%d" % (i + 1)
        raise AssertionError("no face of radius %.3f" % radius)

    def test_creates_a_cut_of_base_and_cutter(self):
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        self.assertEqual(cut_obj.TypeId, "Part::Cut")
        self.assertTrue(cut_obj.Shape.isValid())
        self.assertEqual(len(cut_obj.Shape.Solids), 1)

    def test_the_thread_removes_material(self):
        base = self._bored_block()
        before = base.Shape.Volume
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        self.assertLess(cut_obj.Shape.Volume, before - 1e-6)

    def test_moving_the_base_keeps_the_thread(self):
        """Regression: Part::Cut does not bind Base and Tool placements.

        Without an explicit binding the Cut recomputes to the full uncut
        volume and reports success -- the thread silently vanishes.
        """
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        threaded = cut_obj.Shape.Volume

        base.Placement = App.Placement(App.Vector(50, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertAlmostEqual(cut_obj.Shape.Volume, threaded, places=3)

    def test_rotating_the_base_keeps_the_thread(self):
        """Rotation is why the binding composes placements.

        An expression on Placement.Base.x would translate the cutter but never
        turn it, so a rotated part would come out threaded off-axis.
        """
        base = self._bored_block()
        cut_obj = api.create_thread(
            self.doc, base, self._bore_face(base, 3.4))[1]
        threaded = cut_obj.Shape.Volume

        base.Placement = App.Placement(
            App.Vector(10, 5, 0),
            App.Rotation(App.Vector(1, 1, 0), 37.0))
        self.doc.recompute()
        self.assertAlmostEqual(cut_obj.Shape.Volume, threaded, places=3)

    def test_defaults_pick_M8_for_a_tap_drilled_hole(self):
        base = self._bored_block(bore_radius=3.4)
        circle = selection.resolve(base, self._bore_face(base, 3.4))
        d = api.defaults_for(circle)
        self.assertEqual(d["Mode"], form.INTERNAL)
        self.assertAlmostEqual(d["Diameter"], 8.0, places=3)
        self.assertAlmostEqual(d["Pitch"], 1.25, places=3)

    def test_bad_parameters_raise_rather_than_leaving_junk(self):
        base = self._bored_block()
        before = len(self.doc.Objects)
        with self.assertRaises(Exception):
            api.create_thread(self.doc, base, self._bore_face(base, 3.4),
                              {"Land": 99.0})
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), before,
                         "failed creation left objects behind")
```

Add `from tapdie import selection` to the imports at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `./run_tests.sh fc`
Expected: FAIL — `ModuleNotFoundError: No module named 'tapdie.api'`

- [ ] **Step 3: Write the implementation**

Create `FreeCADTapDie/tapdie/api.py`:

```python
"""Orchestration: selection in, threaded solid out.

This module must never import FreeCADGui -- it is what makes the whole plugin
testable headlessly.
"""

import FreeCAD as App

from . import feature, form, presets, selection


class ThreadError(Exception):
    """The thread could not be created."""


def defaults_for(circle):
    """Sensible starting parameters for a resolved selection."""
    mode = circle.mode or form.INTERNAL
    if mode == form.INTERNAL:
        diameter, pitch = presets.nearest_for_bore(circle.radius * 2.0)
    else:
        diameter, pitch = presets.nearest_for_shaft(circle.radius * 2.0)
    return {
        "Mode": mode,
        "Diameter": diameter,
        "Pitch": pitch,
        "Length": circle.length,
        "SurfaceRadius": circle.radius,
    }


def local_frame(base, circle):
    """The circle's frame expressed in the base part's local coordinates.

    `circle` was read off `base.Shape`, which already has the base's placement
    baked in, so the global frame must be pulled back through it.  Storing the
    LOCAL frame is what lets the cutter follow the base under rotation as well
    as translation.
    """
    rotation = App.Rotation(App.Vector(0, 0, 1), circle.axis)
    world = App.Placement(circle.centre, rotation)
    return base.Placement.inverse().multiply(world)


def create_thread(doc, base, sub_name, overrides=None):
    """Thread `base` at `sub_name`.  Returns (cutter, cut).

    Everything is done inside one undo transaction so a single Ctrl-Z removes
    both objects rather than leaving an orphaned cutter.
    """
    circle = selection.resolve(base, sub_name)
    params = defaults_for(circle)
    params.update(overrides or {})

    doc.openTransaction("Thread")
    created = []
    try:
        cutter_obj = feature.make_cutter(doc)
        created.append(cutter_obj)
        for key, value in params.items():
            setattr(cutter_obj, key, value)

        # The link is what creates the dependency, so the cutter recomputes
        # (and repositions) whenever the base moves.
        cutter_obj.AttachedTo = base
        cutter_obj.LocalPlacement = local_frame(base, circle)
        doc.recompute()

        if not cutter_obj.Shape.isValid() or not cutter_obj.Shape.Solids:
            raise ThreadError(
                "cutter did not build; check Diameter, Pitch and Land")

        cut = doc.addObject("Part::Cut", "Thread")
        created.append(cut)
        cut.Base = base
        cut.Tool = cutter_obj
        doc.recompute()

        # Part::Cut is FreeCAD's, so it cannot be guarded from inside.  A
        # helical boolean is known to return one closed solid that is
        # nevertheless invalid while still reporting Up-to-date.
        if not cut.Shape.isValid():
            raise ThreadError("boolean produced an invalid solid")
        if len(cut.Shape.Solids) != 1:
            raise ThreadError(
                "boolean produced %d solids, expected 1"
                % len(cut.Shape.Solids))

        doc.commitTransaction()
        return cutter_obj, cut
    except Exception:
        doc.abortTransaction()
        for obj in reversed(created):
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
        doc.recompute()
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./run_tests.sh fc`
Expected: PASS — all tests OK, including `test_moving_the_base_keeps_the_thread`

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/api.py tests/test_integration.py
git commit -m "feat: create_thread orchestration with placement binding

Part::Cut keeps Base and Tool placements independent, so the cutter is bound
to the base by expression; without it, moving the part silently un-threads it
while the boolean reports success.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

### Task 8: GUI layer — command, task panel, and Part workbench injection

**Files:**
- Create: `FreeCADTapDie/tapdie/command.py`
- Create: `FreeCADTapDie/InitGui.py`
- Create: `FreeCADTapDie/package.xml`
- Create: `FreeCADTapDie/resources/icons/tapdie_cutter.svg`

**Interfaces:**
- Consumes: `tapdie.api.create_thread`, `tapdie.selection.resolve`
- Produces: Gui command `TapDie_Thread`

This task cannot be verified by `run_tests.sh` — it needs the GUI. Its
verification steps are manual.

- [ ] **Step 1: Write the icon**

Create `FreeCADTapDie/resources/icons/tapdie_cutter.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <rect x="20" y="6" width="24" height="52" fill="#b0b8c4" stroke="#334" stroke-width="2"/>
  <path d="M20 14 L44 20 M20 24 L44 30 M20 34 L44 40 M20 44 L44 50"
        stroke="#334" stroke-width="3" fill="none"/>
</svg>
```

- [ ] **Step 2: Write the command**

Create `FreeCADTapDie/tapdie/command.py`:

```python
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
```

- [ ] **Step 3: Write `InitGui.py`**

Create `FreeCADTapDie/InitGui.py`:

```python
"""Register the tap/die command and inject it into the Part workbench.

addWorkbenchManipulator is the supported way to add commands to a workbench
someone else owns; the bundled BIM workbench uses the same mechanism.
"""

import FreeCADGui as Gui


class TapDieManipulator:
    def modifyMenuBar(self):
        return [{"insert": "TapDie_Thread", "menuItem": "Part_Boolean"}]

    def modifyToolBars(self):
        # The toolbar name below is UNVERIFIED -- the literal "Part tools" does
        # not appear in PartGui.so, and the BIM precedent only implements
        # modifyMenuBar.  If the button does not appear, drop this method; the
        # menu entry alone is a supported fallback.
        return [{"insert": "TapDie_Thread", "toolBar": "Part_Booleans"}]


def _register():
    from tapdie import command      # noqa: F401  (registers the command)
    if not getattr(Gui, "_tapdie_manipulator", None):
        Gui._tapdie_manipulator = TapDieManipulator()
        Gui.addWorkbenchManipulator(Gui._tapdie_manipulator)


_register()
```

- [ ] **Step 4: Write `package.xml`**

Create `FreeCADTapDie/package.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<package format="1" xmlns="https://wiki.freecad.org/Package_Metadata">
  <name>TapDie</name>
  <description>Thread any cylinder by selecting a circular profile.</description>
  <version>0.1.0</version>
  <date>2026-08-02</date>
  <maintainer email="root@init.cx">Alexander</maintainer>
  <license>LGPL-2.1-or-later</license>
  <content>
    <workbench>
      <classname>TapDie</classname>
      <subdirectory>./</subdirectory>
      <icon>resources/icons/tapdie_cutter.svg</icon>
    </workbench>
  </content>
</package>
```

- [ ] **Step 5: Install by symlink and verify the module imports headlessly**

```bash
MOD=~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod
ln -sfn /home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie "$MOD/FreeCADTapDie"
ls -l "$MOD/FreeCADTapDie"
```

Then confirm nothing below the GUI layer got a Gui dependency:

```bash
cat > /home/alexander/Documents/CAD/freecad_tapdie/tests/check_no_gui.py <<'PY'
import sys
sys.path.insert(0, "/home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie")
from tapdie import api, cutter, feature, form, measure, presets, selection
assert "FreeCADGui" not in sys.modules, "a non-GUI module imported FreeCADGui"
print("no-Gui check: ok")
PY
flatpak run --command=freecadcmd org.freecad.FreeCAD \
  /home/alexander/Documents/CAD/freecad_tapdie/tests/check_no_gui.py \
  2>&1 | grep -vE '^FreeCAD 1|^\(C\)|Importing|%\)'
```

Expected: `no-Gui check: ok`

- [ ] **Step 6: Verify in the GUI (manual)**

Launch FreeCAD, switch to the **Part** workbench, and confirm:

1. A `Tap / Die...` entry appears in the Part menu next to the Boolean entries.
2. Whether a toolbar button appears. **If it does not, delete `modifyToolBars`
   from `InitGui.py`** and ship menu-only — do not guess further names.
3. Create a cylinder, select its outer face, run the command, accept the
   defaults, and confirm a `Thread` Cut appears with a `ThreadCutter` child.
4. Select the `ThreadCutter`, change `Pitch`, and confirm the part re-threads.
5. Move the base cylinder and confirm the thread moves with it.

- [ ] **Step 7: Commit**

```bash
git add FreeCADTapDie/InitGui.py FreeCADTapDie/package.xml \
        FreeCADTapDie/tapdie/command.py FreeCADTapDie/resources tests/check_no_gui.py
git commit -m "feat: Gui command and Part workbench injection

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDVXgCpKDvQEPBNQCK7Bjw"
```

---

## Deferred to a follow-up plan

The spec lists two behaviours that need the core working first. They are
deliberately **not** in this plan, and the plan is not complete-in-spirit
without them being scheduled:

1. **Lead-in relief.** A thread cut straight to the face leaves a sharp,
   fragile first turn. `printed_threads/` cuts a 45° lead-in **before** the
   thread, because coning a plain cylinder is trivial while coning a threaded
   one makes OCC return an invalid solid. Needs a `LeadIn` property and correct
   ordering inside `create_thread`.
2. **Stale-cutter detection.** FreeCAD 1.1 blocks the Proxy import when the
   addon is missing, leaving `Proxy = None` with a cached shape. The document
   opens fine, but any later recompute returns success while silently keeping
   the stale shape. Needs a document observer that checks restored
   `ThreadCutter` objects and warns.
