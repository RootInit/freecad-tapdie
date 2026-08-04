# Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six defects and two UI gaps found in the 2026-08-04 code review of the tap/die addon, each with a test that fails before the fix.

**Architecture:** Five of the eight changes are local to one function. The two
that are not — clamping the lead-in cones, and surfacing the real error from a
failed recompute — thread one new value through an existing call path rather
than adding structure. The task panel gains three controls; no new module is
created.

**Tech Stack:** Python 2/3-compatible style as used throughout (`%`
formatting, no f-strings, no type annotations), FreeCAD 1.1 via flatpak,
`unittest`, and the existing `run_tests.sh` harness.

## Global Constraints

- **No FreeCAD import in `form.py` or `presets.py`.** Both are pure Python and
  must stay runnable by `./run_tests.sh pure` without a flatpak.
- **`api.py` must never import `FreeCADGui`.** `command.py` is the only module
  allowed to.
- **Import `Part`/`Sketcher` lazily inside methods**, never at `InitGui.py`
  time.
- **Every behavioural fix gets a test that fails first.** Run the test before
  the fix and confirm the failure message, per `CLAUDE.md`'s "a check that has
  never failed is not known to work".
- **Scripts the flatpak must read live under `/home/alexander`**, never in the
  agent scratchpad.
- Filter FreeCAD stdout noise with `grep -vE '^FreeCAD 1|^\(C\)|Importing|%\)'`.
- Run FreeCAD-backed work with `run_in_background: true`; it exceeds 120s.
- Angle-dependent assertions must be checked at **60 and 90 degrees**, never
  at 90 alone (the 45-degree coincidence).

---

### Task 1: `_detect_free_ends` must fail safe on an unreadable base

**Files:**
- Modify: `FreeCADTapDie/tapdie/feature.py:59-93`
- Test: `tests/test_integration.py` (class `TestFreeEndDetection`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `feature._detect_free_ends(obj)` unchanged in signature, but a base
  whose `Shape` is null or raises now returns `(False, False)` instead of
  `(True, True)`. `AttachedTo is None` still returns `(True, True)`.

- [ ] **Step 1: Write the failing test**

```python
    def test_a_base_with_a_null_shape_reads_as_abutting(self):
        """An unevaluable probe must fail SAFE, like _end_is_free does.

        feature.py's module docstring commits to this: a probe that cannot be
        evaluated is treated as abutting, because gouging a neighbour is
        destructive while a missing overrun merely leaves a plain collar.
        _end_is_free honoured that; _detect_free_ends did not, and returned
        the destructive reading for a base it could not measure.
        """
        ghost = self.doc.addObject("Part::Feature", "Ghost")   # null Shape
        obj = feature.make_cutter(self.doc)
        obj.SurfaceRadius = 4.0
        obj.Length = 6.0
        obj.AttachedTo = ghost
        obj.LocalPlacement = App.Placement()
        self.assertTrue(ghost.Shape.isNull(), "fixture: Ghost must be null")
        self.assertEqual(feature._detect_free_ends(obj), (False, False))

    def test_no_base_at_all_is_still_both_ends_free(self):
        """The other direction: with nothing to gouge, nothing is clamped."""
        obj = feature.make_cutter(self.doc)
        self.assertIsNone(obj.AttachedTo)
        self.assertEqual(feature._detect_free_ends(obj), (True, True))
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `./run_tests.sh fc 2>&1 | grep -A5 null_shape`
Expected: FAIL — `(True, True) != (False, False)`

- [ ] **Step 3: Implement**

In `feature.py`, replace the three early returns in `_detect_free_ends` so only
the no-base case reads free:

```python
    base = getattr(obj, "AttachedTo", None)
    if base is None:
        # Nothing to gouge: an unattached cutter (which is how most of this
        # module's unit tests build one) keeps the pre-detection behaviour.
        return True, True
    # From here there IS a base. Anything we cannot measure about it must
    # read as ABUTTING, matching _end_is_free's own policy and the module
    # docstring above -- a wrong "free" lets the overrun cut into material
    # we simply failed to see, which is the destructive direction.
    try:
        base_shape = base.Shape
    except Exception:
        return False, False
    if base_shape is None or base_shape.isNull():
        return False, False
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh fc`
Expected: PASS, 97 tests, 0 failures

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/feature.py tests/test_integration.py
git commit -m "fix: an unmeasurable base reads as abutting, not free"
```

---

### Task 2: Clamp the lead-in chamfers to the run

**Files:**
- Modify: `FreeCADTapDie/tapdie/feature.py:280-315`
- Test: `tests/test_integration.py` (class `TestFreeEndDetection`)

**Interfaces:**
- Consumes: `cutter.clip_to_axial_range(shape, z_lo, z_hi, radius_reach)`,
  already used for the sweep.
- Produces: no signature change. The cutter's z-extent is now bounded by
  `[z_keep_lo, z_keep_hi]` in the builder frame, chamfers included.

The chamfer's axial reach is `cut_depth + radial_offset`. When that exceeds
`Length`, the free end's cone runs through the opposite end plane. Measured on
a 4mm stub against an 8mm shoulder: cutter z-extent `[-0.6959, 1.0442]` for a
run of `[0, 1]`, removing 0.3697mm from the shoulder.

- [ ] **Step 1: Write the failing test**

```python
    def test_a_chamfer_never_reaches_past_an_abutting_end(self):
        """The clamp must bound the CHAMFERS too, not only the sweep.

        Measured before the fix: a 4mm stub against an 8mm shoulder, run
        [0, 1], chamfer reach 1.6697mm -> cutter z-extent [-0.6959, 1.0442]
        and 0.3697mm of the shoulder eaten. feature.py claimed the chamfer
        "sits entirely within [feature_lo, feature_hi]"; it does not once the
        run is shorter than the chamfer's own reach.
        """
        stub = Part.makeCylinder(4.0, 1.0, App.Vector(0, 0, 0))
        shoulder = Part.makeCylinder(8.0, 5.0, App.Vector(0, 0, -5.0))
        base = self.doc.addObject("Part::Feature", "Stub")
        base.Shape = stub.fuse(shoulder).removeSplitter()
        self.doc.recompute()

        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 3.8
        obj.SurfaceRadius = 4.0
        obj.Length = 1.0
        obj.Direction = form.FORWARD          # run occupies z in [0, +1]
        obj.LeadIn = True
        obj.FlushEnds = True
        obj.AttachedTo = base
        obj.LocalPlacement = App.Placement()
        self.doc.recompute()

        self.assertFalse(obj.NearEndFree, "fixture: z=0 abuts the shoulder")
        self.assertTrue(obj.FarEndFree, "fixture: z=+1 is open air")
        box = obj.Shape.optimalBoundingBox()
        self.assertGreaterEqual(
            box.ZMin, -1e-6,
            "the chamfer reached %.4fmm past the abutting end at z=0"
            % -box.ZMin)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `./run_tests.sh fc 2>&1 | grep -A6 never_reaches_past`
Expected: FAIL — `the chamfer reached 0.6959mm past the abutting end at z=0`

- [ ] **Step 3: Implement**

In `feature.py`, replace the comment block's false claim and clip each cone.
Change lines 286-290 of the comment to state the real behaviour, then:

```python
        if obj.LeadIn and (near_free or far_free):
            tip_radius = points[0][0]
            reach = max(pt[0] for pt in points)
            if near_free:
                extras.append(cutter.clip_to_axial_range(
                    cutter.lead_in_cone(tip_radius, obj.SurfaceRadius.Value,
                                        feature_lo, into_material=True),
                    z_keep_lo, z_keep_hi, reach))
            if far_free:
                extras.append(cutter.clip_to_axial_range(
                    cutter.lead_in_cone(tip_radius, obj.SurfaceRadius.Value,
                                        feature_hi, into_material=False),
                    z_keep_lo, z_keep_hi, reach))
```

And replace the false sentence in the preceding comment with:

```python
        # A cone's axial reach EQUALS its radial depth (it is 45 degrees), so
        # on a run shorter than cut_depth + radial_offset it crosses the far
        # end plane. Measured: a 1mm run at pitch 3.8 put the cutter at
        # z in [-0.6959, 1.0442] and took 0.3697mm out of the shoulder the
        # abutting-end clamp exists to protect. So the cones are clipped to
        # the same [z_keep_lo, z_keep_hi] as the sweep. Where the run is long
        # enough -- every ordinary case -- the clip is a no-op.
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh fc`
Expected: PASS. `test_very_short_feature_where_chamfers_overlap_still_builds`
(Length=1.0, both ends free) still passes: it asserts validity, not volume.

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/feature.py tests/test_integration.py
git commit -m "fix: clamp lead-in chamfers to the run, not just the sweep"
```

---

### Task 3: Surface the real reason a recompute failed

**Files:**
- Modify: `FreeCADTapDie/tapdie/feature.py:227-232` (wrap `execute`)
- Modify: `FreeCADTapDie/tapdie/api.py:67-87` (`_check_recomputed`)
- Test: `tests/test_integration.py` (class `TestCreateThread`)

**Interfaces:**
- Produces: `ThreadCutter.last_error` — `str` after a failed `execute()`,
  `None` after a successful one. `api._check_recomputed` appends it to the
  `ThreadError` message when present.

Measured: a 0.9mm bore failed with `cutter overrun 1.0000 reaches through the
axis from a bore at r=0.9000`, and the panel showed only "check Diameter,
Pitch and the lands" — advice that cannot fix it.

- [ ] **Step 1: Write the failing test**

```python
    def test_the_real_profile_error_reaches_the_caller(self):
        """A generic 'check Diameter, Pitch and the lands' is not a diagnosis.

        The overrun-through-the-axis case is the motivating one: none of the
        three things the old message named can fix it.
        """
        doc = self.doc
        obj = feature.make_cutter(doc)
        obj.Mode = form.INTERNAL
        obj.SurfaceRadius = 0.9
        obj.Overrun = 1.0
        doc.recompute()
        with self.assertRaises(api.ThreadError) as caught:
            api._validate(obj, None)
        self.assertIn("overrun", str(caught.exception))
        self.assertIn("0.9000", str(caught.exception))

    def test_a_successful_rebuild_clears_the_previous_error(self):
        doc = self.doc
        obj = feature.make_cutter(doc)
        obj.Mode = form.INTERNAL
        obj.SurfaceRadius = 0.9
        doc.recompute()
        self.assertIsNotNone(obj.Proxy.last_error)
        obj.SurfaceRadius = 8.2597
        doc.recompute()
        self.assertIsNone(obj.Proxy.last_error)
        api._validate(obj, None)      # must not raise
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `./run_tests.sh fc 2>&1 | grep -A6 real_profile_error`
Expected: FAIL — `'overrun' not found in 'cutter did not build (recompute
left it Invalid, Touched); check Diameter, Pitch and the lands'`

- [ ] **Step 3: Implement**

In `feature.py`, rename the existing `execute` body to `_build_shape` and add
a recording wrapper:

```python
    def execute(self, obj):
        # FreeCAD swallows whatever execute() raises: it marks the object
        # Invalid and writes the traceback to the Report view, and the
        # exception never reaches doc.recompute()'s caller. api._validate
        # therefore had nothing but the State to go on and had to GUESS at a
        # cause -- it told a user whose 0.9mm bore was smaller than the 1.0mm
        # Overrun to "check Diameter, Pitch and the lands", none of which
        # could fix it. Record the message on the way past so the panel can
        # show the real one.
        try:
            self._build_shape(obj)
        except Exception as exc:
            self.last_error = str(exc)
            raise
        self.last_error = None

    def _build_shape(self, obj):
        ...   # the whole of the current execute() body, unchanged
```

Add `self.last_error = None` to `ThreadCutter.__init__` before
`self.add_properties(obj)`, and to `onDocumentRestored` (a restored proxy has
no such attribute).

In `api.py`, use it:

```python
def _check_recomputed(obj, what):
    state = set(obj.State)
    if "Invalid" in state or "Touched" in state or "Error" in state:
        # feature.ThreadCutter records what execute() actually raised; a
        # Part::Cut has no Proxy and falls back to the generic advice.
        detail = getattr(getattr(obj, "Proxy", None), "last_error", None)
        if detail:
            raise ThreadError("%s did not build: %s" % (what, detail))
        raise ThreadError(
            "%s did not build (recompute left it %s); check Diameter, Pitch "
            "and the lands" % (what, ", ".join(sorted(state))))
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh fc`
Expected: PASS. Check `test_null_shape_is_reported_clearly` and
`test_bad_parameters_raise_rather_than_leaving_junk` still pass — if either
matched on the old wording, update it to match the new message rather than
weakening the assertion.

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/feature.py FreeCADTapDie/tapdie/api.py tests/test_integration.py
git commit -m "fix: report what execute() actually raised, not a guess"
```

---

### Task 4: A failed preview must not leave an orphan cutter

**Files:**
- Modify: `FreeCADTapDie/tapdie/command.py:174-192` (`_build`)
- Test: `tools/diag_preview.py` (new section)
- Modify: `run_tests.sh` (add a `diag` target)

**Interfaces:**
- Produces: `ThreadTaskPanel._build()` now discards anything left in
  `self.created` before building, and opens a transaction only if one is not
  already open.

Measured through the real panel offscreen: first preview fails, user switches
Mode, Refresh succeeds, OK commits — and `ThreadCutter` (Invalid, consumed by
nothing) stays in the tree beside `ThreadCutter001` forever.

- [ ] **Step 1: Write the failing check**

Append to `tools/diag_preview.py`, before the final summary block:

```python
# --- a failed first preview must not strand a cutter -----------------------
# Measured before the fix: _build() appends the cutter to self.created BEFORE
# validating, so a failure leaves it in the document with self.cutter_obj
# still None. _rebuild() then sees None and calls _build() AGAIN, making a
# second cutter; accept() consumes only that one and commits the first as an
# orphan. A 0.6mm shaft fails at the default 0.12 clearance (the profile's
# tip lands at r<0) and builds at clearance 0, so the whole cycle is
# reachable with the dialog's own controls.
doc3 = App.newDocument("orphan")
App.setActiveDocument(doc3.Name)
base3, sub3 = shaft(doc3, radius=0.3, height=6.0)
baseline3 = {o.Name for o in doc3.Objects}
panel3, _c3 = panel_for(doc3, base3, sub3)
check("a 0.6mm shaft fails the first preview", not panel3.preview_ok,
      panel3.note.text())
check("the failed preview left nothing behind",
      len({o.Name for o in doc3.Objects} - baseline3) == 0,
      "left: %s" % sorted({o.Name for o in doc3.Objects} - baseline3))
panel3.clearance.setValue(0.0)
guarded("Refresh after the failure", panel3._rebuild)
check("clearance 0 makes it build", panel3.preview_ok, panel3.note.text())
check("accept() applies", guarded("accept() after recovery",
                                  panel3.accept) is True)
doc3.recompute()
cutters3 = [o for o in doc3.Objects
            if getattr(getattr(o, "Proxy", None), "Type", None)
            == "ThreadCutter"]
check("exactly one cutter survives a failed-then-fixed preview",
      len(cutters3) == 1, "cutters: %s" % [o.Name for o in cutters3])
for c in cutters3:
    consumed = [o.Name for o in doc3.Objects
                if getattr(o, "Tool", None) is c]
    check("the surviving cutter is consumed by the boolean",
          bool(consumed), "%s consumed_by=%s" % (c.Name, consumed or "NOTHING"))
```

- [ ] **Step 2: Run it and confirm it fails**

Run in background:
`flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD tools/diag_preview.py; cat tools/diag_preview.log`
Expected: FAIL — `exactly one cutter survives a failed-then-fixed preview
... cutters: ['ThreadCutter', 'ThreadCutter001']`

- [ ] **Step 3: Implement**

In `command.py`, replace the head of `_build`:

```python
    def _build(self):
        """Create the preview CUTTER inside an undo transaction.

        No boolean here -- see the class docstring.
        """
        from . import api

        doc = self.doc
        # A previous attempt that failed left its half-built cutter in the
        # document and in self.created, while self.cutter_obj stayed None --
        # so _rebuild() routes back here and would build a SECOND one, and
        # accept() would consume only that, committing the first as an
        # orphan (measured: ThreadCutter Invalid, consumed by nothing,
        # beside a working ThreadCutter001). Clear the wreckage first.
        if self.created:
            api.discard(doc, *reversed(self.created))
            self.created = []
        # _build can run more than once for the same dialog, and a second
        # openTransaction would close the first, orphaning its undo entry.
        if not self.transaction_open:
            doc.openTransaction("Thread")
            self.transaction_open = True
        try:
            self.cutter_obj = api.build_cutter(
                doc, self.base, self.sub_name, self.overrides(), self.created)
            self.preview_ok = True
        except self._errors() as exc:
            self.preview_ok = False
            self._say(exc)
        else:
            self._say(None)
```

- [ ] **Step 4: Run the diag and confirm it passes**

Run: same command as Step 2.
Expected: `PREVIEW DIAG: 0 failure(s)`

- [ ] **Step 5: Wire the diag into the harness**

In `run_tests.sh`, add a `diag` case and include it in `all`:

```sh
  diag)
    # The offscreen GUI is the only thing that exercises the task panel,
    # command registration and the undo transaction. Same output-capture
    # dance as `fc`: /bin/sh has no pipefail.
    out="$ROOT/.fc-test-output"
    trap 'rm -f "$out"' EXIT INT TERM
    set +e
    flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD \
        "$ROOT/tools/diag_preview.py" > "$out" 2>&1
    status=$?
    set -e
    cat "$ROOT/tools/diag_preview.log" 2>/dev/null || true
    exit "$status"
    ;;
```

and change `all)` to `"$0" pure && "$0" fc && "$0" diag`.

- [ ] **Step 6: Commit**

```bash
git add FreeCADTapDie/tapdie/command.py tools/diag_preview.py run_tests.sh
git commit -m "fix: a failed preview no longer strands a cutter in the tree"
```

---

### Task 5: `crest_relief` takes the mode explicitly

**Files:**
- Modify: `FreeCADTapDie/tapdie/cutter.py:166-211`
- Modify: `FreeCADTapDie/tapdie/feature.py` (the `crest_relief` call)
- Test: `tests/test_cutter.py`

**Interfaces:**
- Produces: `cutter.crest_relief(mode, surface_radius, crest_radius, z_lo,
  z_hi, overrun)` — `mode` is a new FIRST parameter taking `form.INTERNAL` or
  `form.EXTERNAL`. Every caller must be updated.

- [ ] **Step 1: Write the failing test**

```python
    def test_external_relief_is_decided_by_mode_not_by_the_radius_sign(self):
        """A negative Clearance used to invert the branch silently.

        crest_relief inferred EXTERNAL from `crest_radius < surface_radius`.
        That holds for every reachable input today, but it means the function
        cannot tell "external with a negative clearance" from "internal", and
        would relieve a shaft OUTWARDS -- removing material below the
        surface. Mode is known at the call site; pass it.
        """
        solid = cutter.crest_relief(form.EXTERNAL, 4.0, 4.2, 0.0, 5.0, 1.0)
        box = solid.optimalBoundingBox()
        # An external relief never reaches inside the crest radius...
        self.assertGreaterEqual(box.XMax, 4.2 - 1e-6)
        # ...and an internal one at the same numbers spans the other way.
        internal = cutter.crest_relief(form.INTERNAL, 4.0, 4.2, 0.0, 5.0, 1.0)
        self.assertGreater(internal.Volume, 0.0)

    def test_crest_relief_rejects_an_unknown_mode(self):
        with self.assertRaises(cutter.CutterError) as caught:
            cutter.crest_relief("Sideways", 4.0, 3.8, 0.0, 5.0, 1.0)
        self.assertIn("Sideways", str(caught.exception))
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `./run_tests.sh fc 2>&1 | grep -A5 decided_by_mode`
Expected: FAIL — `TypeError: crest_relief() takes 5 positional arguments but 6 were given`

- [ ] **Step 3: Implement**

In `cutter.py`, add the parameter and branch on it. Import `form` at module
scope is fine here — `cutter.py` already imports FreeCAD, and `form` is pure:

```python
from . import form


def crest_relief(mode, surface_radius, crest_radius, z_lo, z_hi, overrun):
    """A cylindrical shell that takes the surface down (or out) to the crest.

    ... (keep the existing docstring body) ...

    `mode` decides which way the shell spans. It used to be inferred from
    `crest_radius < surface_radius`, which is true for every reachable input
    but silently inverts under a negative clearance -- and an inverted
    external relief removes the shaft from below its own surface. The caller
    knows the mode; there is no reason to re-derive it.
    """
    if mode not in (form.INTERNAL, form.EXTERNAL):
        raise CutterError(
            "mode %r is not %s or %s" % (mode, form.INTERNAL, form.EXTERNAL))
    if z_hi <= z_lo:
        raise CutterError(
            "crest relief range [%.4f, %.4f] is empty or inverted"
            % (z_lo, z_hi))
    if abs(crest_radius - surface_radius) < 1e-9:
        return None
    if crest_radius <= 0.0:
        raise CutterError(
            "crest relief would take the surface to r=%.4f, at or through "
            "the axis" % crest_radius)

    # Span from the relieved surface out past the original one, so the shell
    # certainly reaches material at every azimuth.
    if mode == form.EXTERNAL:                    # shave the shaft
        r_lo, r_hi = min(crest_radius, surface_radius), surface_radius + overrun
    else:                                        # open the bore
        r_lo = max(min(surface_radius, crest_radius) - overrun, 1e-6)
        r_hi = max(crest_radius, surface_radius)
```

In `feature.py`, pass the mode:

```python
        relief = cutter.crest_relief(
            obj.Mode,
            obj.SurfaceRadius.Value,
            form.crest_radius(obj.Mode, obj.SurfaceRadius.Value,
                              obj.Clearance.Value, obj.Angle.Value),
            z_keep_lo, z_keep_hi, obj.Overrun.Value)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh fc`
Expected: PASS. Any existing `crest_relief` call in `tests/test_cutter.py`
needs the new first argument.

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/cutter.py FreeCADTapDie/tapdie/feature.py tests/test_cutter.py
git commit -m "fix: crest_relief branches on Mode, not the sign of a radius"
```

---

### Task 6: Make `Diameter` a real check

**Files:**
- Modify: `FreeCADTapDie/tapdie/form.py` (add `achieved_diameter`)
- Modify: `FreeCADTapDie/tapdie/api.py` (add `diameter_note`)
- Modify: `FreeCADTapDie/tapdie/command.py:217-242` (`_say`)
- Test: `tests/test_form.py`, `tests/test_integration.py`

**Interfaces:**
- Produces:
  - `form.achieved_diameter(mode, pitch, angle, root_land, crest_land,
    clearance, surface_radius)` -> `float`. Exact inverse of
    `required_surface_radius`; verified round-trip to 1e-9 across the whole
    ISO coarse table in both modes and both forms.
  - `api.DIAMETER_TOLERANCE = 0.1` (mm).
  - `api.diameter_note(cutter_obj)` -> `str` or `None`. `None` when the
    achieved diameter is within tolerance of the requested one.

`Diameter` is passed to `form.cutter_points` and never read — measured
identical output for 8.0 and 24.0. `required_surface_radius` exists to detect
exactly this and has no production caller.

Tolerance rationale, measured: `required_surface_radius` and
`achieved_diameter` round-trip exactly, so any reported mismatch is real. A
standard 6.6mm M8 tap drill yields Ø8.08 on the printed form — a genuine 0.08
overshoot that should not nag, so the threshold sits just above it at 0.1mm.

- [ ] **Step 1: Write the failing tests**

In `tests/test_form.py`:

```python
class TestAchievedDiameter(unittest.TestCase):
    """The inverse of required_surface_radius, swept across angles.

    Both directions are checked at 60 AND 90 degrees: at 90 the flank
    half-angle coincidences make a wrong convention indistinguishable from a
    right one (see CLAUDE.md), so a single-angle test proves nothing.
    """

    def test_round_trips_against_required_surface_radius(self):
        for angle in (60.0, 90.0, 120.0):
            for mode in (form.INTERNAL, form.EXTERNAL):
                for pitch in (0.5, 1.25, 3.8):
                    r = form.required_surface_radius(
                        mode, 8.0, pitch, angle, 0.1, 0.1, 0.12)
                    got = form.achieved_diameter(
                        mode, pitch, angle, 0.1, 0.1, 0.12, r)
                    self.assertAlmostEqual(
                        got, 8.0, places=9,
                        msg="mode=%s angle=%s pitch=%s" % (mode, angle, pitch))

    def test_an_external_thread_is_its_own_shaft(self):
        self.assertAlmostEqual(
            form.achieved_diameter(form.EXTERNAL, 1.25, 90.0, 0.2, 0.2,
                                   0.12, 10.0),
            20.0, places=9)

    def test_an_internal_thread_is_larger_than_its_bore(self):
        got = form.achieved_diameter(form.INTERNAL, 1.25, 90.0, 0.2, 0.2,
                                     0.12, 5.0)
        self.assertGreater(got, 10.0)

    def test_an_unknown_mode_raises(self):
        with self.assertRaises(form.ProfileError) as caught:
            form.achieved_diameter("Sideways", 1.25, 90.0, 0.2, 0.2, 0.12, 5.0)
        self.assertIn("Sideways", str(caught.exception))
```

In `tests/test_integration.py`:

```python
    def test_a_matching_blank_reports_nothing(self):
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.Diameter = 8.0
        obj.SurfaceRadius = 4.0
        self.doc.recompute()
        self.assertIsNone(api.diameter_note(obj))

    def test_a_mismatched_blank_says_what_it_will_actually_cut(self):
        """The whole point of finding 1: Diameter drove nothing at all."""
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.EXTERNAL
        obj.Diameter = 16.0
        obj.SurfaceRadius = 10.0      # a 20mm shaft
        self.doc.recompute()
        note = api.diameter_note(obj)
        self.assertIsNotNone(note)
        self.assertIn("20.00", note)
        self.assertIn("16.00", note)

    def test_a_tap_drilled_M8_bore_is_within_tolerance(self):
        """0.08mm of overshoot is real but must not nag on the common case."""
        obj = feature.make_cutter(self.doc)
        obj.Mode = form.INTERNAL
        obj.ThreadForm = form.PRINTED
        obj.Pitch = 1.25
        obj.Diameter = 8.0
        obj.SurfaceRadius = 3.3        # 6.6mm tap drill
        self.doc.recompute()
        self.assertIsNone(api.diameter_note(obj))
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `./run_tests.sh pure 2>&1 | grep -A4 achieved` then `./run_tests.sh fc 2>&1 | grep -A4 diameter_note`
Expected: FAIL — `AttributeError: module 'tapdie.form' has no attribute 'achieved_diameter'`

- [ ] **Step 3: Implement**

In `form.py`, after `required_surface_radius`:

```python
def achieved_diameter(mode, pitch, angle, root_land, crest_land, clearance,
                      surface_radius):
    """Nominal major diameter this cutter really produces on `surface_radius`.

    The exact inverse of required_surface_radius, and the check that makes
    `Diameter` mean something. The profile is anchored on the SURFACE, so a
    blank of the wrong size yields a correctly shaped thread of the wrong
    size -- silently, until something computes this and compares.
    """
    if mode not in (INTERNAL, EXTERNAL):
        raise ProfileError(
            "mode %r is not %s or %s" % (mode, INTERNAL, EXTERNAL))
    if mode == EXTERNAL:
        return 2.0 * surface_radius
    return 2.0 * (surface_radius
                  + cut_depth(pitch, angle, root_land, crest_land)
                  + 2.0 * radial_offset(clearance, angle))
```

In `api.py`:

```python
# How far the thread a cutter really produces may drift from the Diameter
# asked for before it is worth saying so, in mm. Measured: the two are exact
# inverses, so any drift is real -- but a standard 6.6mm M8 tap drill legally
# yields 8.08mm on the printed form, and nagging about that on the commonest
# selection there is would train the user to ignore the line.
DIAMETER_TOLERANCE = 0.1


def diameter_note(cutter_obj):
    """What this cutter will really produce, when that is not what was asked.

    Returns None when they agree. `Diameter` positions nothing -- the surface
    does -- so without this the field was inert: a user threading a 20mm
    shaft could set Diameter to 16 and get an M20 thread with no warning.
    """
    mode = cutter_obj.Mode
    got = form.achieved_diameter(
        mode, cutter_obj.Pitch.Value, cutter_obj.Angle.Value,
        cutter_obj.RootLand.Value, cutter_obj.CrestLand.Value,
        cutter_obj.Clearance.Value, cutter_obj.SurfaceRadius.Value)
    want = cutter_obj.Diameter.Value
    if abs(got - want) <= DIAMETER_TOLERANCE:
        return None
    needed = 2.0 * form.required_surface_radius(
        mode, want, cutter_obj.Pitch.Value, cutter_obj.Angle.Value,
        cutter_obj.RootLand.Value, cutter_obj.CrestLand.Value,
        cutter_obj.Clearance.Value)
    surface = "shaft" if mode == form.EXTERNAL else "bore"
    return ("This cuts a %.2fmm thread, not %.2fmm: the selected %s is "
            "%.2fmm and a %.2fmm thread needs a %.2fmm one."
            % (got, want, surface, 2.0 * cutter_obj.SurfaceRadius.Value,
               want, needed))
```

In `command.py`, show it in `_say`, after the stale branch and before the
form-specific advice:

```python
        self.note.setStyleSheet("")
        note = None
        if self.cutter_obj is not None and self.preview_ok:
            from . import api
            note = api.diameter_note(self.cutter_obj)
        if note is not None:
            self.note.setText(note)
            self.note.setStyleSheet("color: #b9770e;")
            return
        if self.thread_form.currentText() == form.ISO:
            ...
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh`
Expected: PASS across all three halves.

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/form.py FreeCADTapDie/tapdie/api.py FreeCADTapDie/tapdie/command.py tests/test_form.py tests/test_integration.py
git commit -m "feat: warn when the blank will not produce the Diameter asked for"
```

---

### Task 7: Expose Overrun, and default it from the selection

**Files:**
- Modify: `FreeCADTapDie/tapdie/api.py` (`defaults_for`)
- Modify: `FreeCADTapDie/tapdie/command.py` (widget + `overrides`)
- Test: `tests/test_integration.py`, `tools/diag_preview.py`

**Interfaces:**
- Produces: `defaults_for(circle)` gains an `"Overrun"` key. For INTERNAL it
  is `min(1.0, 0.5 * circle.radius)`; for EXTERNAL it stays `1.0`.

A bore smaller than the fixed 1.0mm Overrun could not be threaded at all, and
the dialog had no control to fix it — measured on a 0.9mm-radius bore.

- [ ] **Step 1: Write the failing test**

```python
    def test_a_small_bore_gets_an_overrun_it_can_survive(self):
        """Overrun 1.0 reaches through the axis of any bore under r=1."""
        circle = selection.Circle(centre=App.Vector(), axis=App.Vector(0, 0, 1),
                                  radius=0.9, mode=form.INTERNAL,
                                  length=10.0, direction=form.BOTH)
        self.assertLess(api.defaults_for(circle)["Overrun"], 0.9)

    def test_a_shaft_keeps_the_full_overrun(self):
        circle = selection.Circle(centre=App.Vector(), axis=App.Vector(0, 0, 1),
                                  radius=0.9, mode=form.EXTERNAL,
                                  length=10.0, direction=form.BOTH)
        self.assertEqual(api.defaults_for(circle)["Overrun"], 1.0)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `./run_tests.sh fc 2>&1 | grep -A4 small_bore`
Expected: FAIL — `KeyError: 'Overrun'`

- [ ] **Step 3: Implement**

In `api.defaults_for`, add:

```python
    # The cutter's parallel section runs `Overrun` past the surface. For a
    # bore that is INWARD, towards the axis, so a fixed 1.0mm reached through
    # the middle of anything under r=1 and form.cutter_points rejected it --
    # with no dialog control able to fix it. Half the radius always clears.
    overrun = 1.0 if mode == form.EXTERNAL else min(1.0, 0.5 * circle.radius)
```

and include `"Overrun": overrun` in the returned dict.

In `command.py`, add the control after Clearance:

```python
        self.overrun = QtGui.QDoubleSpinBox()
        self.overrun.setRange(0.01, 20.0)
        self.overrun.setDecimals(3)
        self.overrun.setSingleStep(0.1)
        self.overrun.setValue(defaults.get("Overrun", 1.0))
        self.overrun.setToolTip(
            "How far the cutter reaches past the surface it is cutting.\n"
            "For a bore this runs towards the axis, so it must stay under "
            "the bore radius.")
        layout.addRow("Overrun", self.overrun)
```

add it to the `valueChanged` connection list alongside `self.clearance`, and
to `overrides()`: `"Overrun": self.overrun.value(),`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `./run_tests.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/api.py FreeCADTapDie/tapdie/command.py tests/test_integration.py
git commit -m "feat: expose Overrun and scale its default to the bore"
```

---

### Task 8: Give Custom its own controls

**Files:**
- Modify: `FreeCADTapDie/tapdie/command.py`
- Test: `tools/diag_preview.py` (new section)

**Interfaces:**
- Produces: `ThreadTaskPanel.angle`, `.root_land`, `.crest_land` — three
  `QDoubleSpinBox`es, enabled only while Form is Custom. `overrides()` includes
  `Angle`/`RootLand`/`CrestLand` **only** when Form is Custom, so a preset is
  never fought.

Measured: switching to Custom at pitch 0.5 leaves the previous preset's
0.4mm lands against a 0.5mm pitch, so the preview cannot build and no dialog
control can recover it.

- [ ] **Step 1: Write the failing check**

Append to `tools/diag_preview.py`, before the summary:

```python
# --- Custom form is usable ---------------------------------------------------
# Measured before the fix: picking Custom froze whatever the last preset left,
# so Custom at a fine pitch kept 0.4mm lands against a 0.5mm pitch, the
# preview died with "leaves no flank within the pitch", and the dialog had no
# control able to fix it.
doc4 = App.newDocument("customform")
App.setActiveDocument(doc4.Name)
base4, sub4 = shaft(doc4, radius=4.0, height=20.0)
panel4, _c4 = panel_for(doc4, base4, sub4)
check("preset hides the custom controls", not panel4.angle.isEnabled())
panel4.thread_form.setCurrentText(form.CUSTOM)
check("Custom enables the angle control", panel4.angle.isEnabled())
check("Custom enables both land controls",
      panel4.root_land.isEnabled() and panel4.crest_land.isEnabled())
check("Custom seeds itself from the preset it replaced",
      panel4.angle.value() > 0.0 and panel4.root_land.value() > 0.0,
      "angle=%.2f root=%.4f" % (panel4.angle.value(),
                                panel4.root_land.value()))
panel4.pitch.setValue(0.5)
panel4.root_land.setValue(0.02)
panel4.crest_land.setValue(0.02)
panel4.angle.setValue(60.0)
guarded("Refresh with custom values", panel4._rebuild)
check("Custom at a fine pitch builds", panel4.preview_ok, panel4.note.text())
check("the custom angle actually reached the feature",
      abs(panel4.cutter_obj.Angle.Value - 60.0) < 1e-6,
      "Angle=%s" % panel4.cutter_obj.Angle.Value)
check("the custom lands actually reached the feature",
      abs(panel4.cutter_obj.RootLand.Value - 0.02) < 1e-6,
      "RootLand=%s" % panel4.cutter_obj.RootLand.Value)
panel4.thread_form.setCurrentText(form.PRINTED)
guarded("Refresh back on a preset", panel4._rebuild)
check("switching back to a preset retakes the angle",
      abs(panel4.cutter_obj.Angle.Value - 90.0) < 1e-6,
      "Angle=%s" % panel4.cutter_obj.Angle.Value)
guarded("reject() the custom panel", panel4.reject)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD tools/diag_preview.py; cat tools/diag_preview.log`
Expected: FAIL — `AttributeError: 'ThreadTaskPanel' object has no attribute 'angle'`

- [ ] **Step 3: Implement**

In `command.py.__init__`, after the Form combo:

```python
        # Angle and the two lands are preset-driven, so they are shown but
        # disabled unless Form is Custom -- the same lock feature.py puts on
        # the properties themselves. Without them Custom was a dead end:
        # it froze whatever the last preset left, so Custom at a fine pitch
        # kept lands wider than the pitch and nothing in the dialog could
        # recover it.
        self.angle = QtGui.QDoubleSpinBox()
        self.angle.setRange(10.5, 169.5)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        self.angle.setToolTip(
            "Included angle. 90 puts every flank at the 45 degree overhang "
            "limit, which is the FDM optimum; ISO's 60 droops when printed "
            "axis-vertical.")
        layout.addRow("Angle", self.angle)

        self.root_land = QtGui.QDoubleSpinBox()
        self.root_land.setRange(0.001, 10.0)
        self.root_land.setDecimals(4)
        self.root_land.setSingleStep(0.01)
        self.root_land.setToolTip("Flat at the bottom of the groove.")
        layout.addRow("Root land", self.root_land)

        self.crest_land = QtGui.QDoubleSpinBox()
        self.crest_land.setRange(0.001, 10.0)
        self.crest_land.setDecimals(4)
        self.crest_land.setSingleStep(0.01)
        self.crest_land.setToolTip(
            "Flat left on the surface between grooves.")
        layout.addRow("Crest land", self.crest_land)
```

Seed them and wire the enable/disable. Add this method:

```python
    def _sync_form_controls(self):
        """Enable Angle/lands for Custom only, seeding them from the preset.

        Seeding matters: an empty or stale Custom is how the dead end
        happened -- lands left at a coarse preset's 0.4mm against a 0.5mm
        pitch leave no flank within the pitch, and cutter_points rejects it.
        """
        from . import form, presets

        custom = self.thread_form.currentText() == form.CUSTOM
        if not custom:
            defaults = presets.form_defaults(
                self.thread_form.currentText(), self.pitch.value(),
                self.mode.currentText())
            self.angle.setValue(defaults["angle"])
            self.root_land.setValue(defaults["root_land"])
            self.crest_land.setValue(defaults["crest_land"])
        for widget in (self.angle, self.root_land, self.crest_land):
            widget.setEnabled(custom)
```

Call `self._sync_form_controls()` once at the end of `__init__` (before
`self._build()`), and from `_touch()`:

```python
    def _touch(self):
        """Mark the preview out of date without rebuilding it."""
        self._sync_form_controls()
        self.stale = True
        self._say(None)
```

Connect the three new widgets to `_touch` in the `valueChanged` loop, and
extend `overrides()`:

```python
        values = {
            "Mode": self.mode.currentText(),
            ...
        }
        # Only when Custom: on a preset these three are computed by
        # feature._apply_preset, and sending them would just fight it.
        if self.thread_form.currentText() == form.CUSTOM:
            values["Angle"] = self.angle.value()
            values["RootLand"] = self.root_land.value()
            values["CrestLand"] = self.crest_land.value()
        return values
```

Note `api.apply_params` already sets `Mode`/`ThreadForm`/`Pitch`/`Diameter`
first, so these three land after the preset machinery has run — no ordering
change is needed.

- [ ] **Step 4: Run the diag and confirm it passes**

Run: `./run_tests.sh diag`
Expected: `PREVIEW DIAG: 0 failure(s)`

- [ ] **Step 5: Commit**

```bash
git add FreeCADTapDie/tapdie/command.py tools/diag_preview.py
git commit -m "feat: Custom form gets angle and land controls"
```

---

### Task 9: Keep the review probes, refresh the docs

**Files:**
- Create: `tools/probe_diameter.py`, `tools/probe_chamfer_overreach.py`
- Modify: `README.md`
- Modify: `FreeCADTapDie/package.xml` (version bump)

`CLAUDE.md`: "Keep it: `tools/probe_*.py` and `tools/diag_*.py` are cheap and
the findings do not survive in your head."

- [ ] **Step 1: Move the two probes that found real defects into `tools/`**

Take the `Diameter` probe and the chamfer-overreach probe from
`/home/alexander/tapdie_probe_review*.py`, each as a standalone script with
the docstring stating what it measured and the number it found.

- [ ] **Step 2: Update the README**

The "Known limitation" list gains nothing (the Ctrl-Z one stands), but the
"Things worth knowing" section needs a line about Diameter being a check
rather than a driver, and the Tests section needs `./run_tests.sh diag`.

- [ ] **Step 3: Bump the version**

`package.xml` `<version>` 0.1.0 -> 0.1.1, and `<date>` to 2026-08-04.

- [ ] **Step 4: Run everything**

Run: `./run_tests.sh`
Expected: all three halves pass.

- [ ] **Step 5: Commit and push**

```bash
git add tools/ README.md FreeCADTapDie/package.xml
git commit -m "docs: keep the review probes, note the Diameter check"
git push
```

---

## Self-Review

**Spec coverage.** Review findings 1-8 map to tasks: 1 -> Task 6, 2 -> Task 4,
3 -> Task 2, 4 -> Task 1, 5 -> Task 3, 6 -> Task 8, 7 -> Task 7, 8 -> Task 5.
Task 9 is housekeeping. No finding is unassigned.

**Ordering.** Task 7 (Overrun default) changes whether a small bore builds, so
it must come *after* Task 4, whose repro depends on a first preview failing.
Task 4's repro uses a 0.6mm **shaft** and clearance, not a bore, so it stays
valid either way — but the ordering is kept for safety. Task 3 changes an
error message that Task 4's diag prints; Task 4 asserts on `preview_ok`, not
on the wording, so they are independent.

**Type consistency.** `crest_relief` gains `mode` as its first parameter in
Task 5 and every call site is listed. `achieved_diameter` and `diameter_note`
are defined in Task 6 and used only there and in `command._say`.
`last_error` is set in Task 3's `execute` and read in Task 3's
`_check_recomputed`. `_sync_form_controls` is defined and called in Task 8.
