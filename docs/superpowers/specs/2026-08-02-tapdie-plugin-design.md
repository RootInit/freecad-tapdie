# FreeCAD tap/die plugin — design

**Date:** 2026-08-02
**Status:** revised after review; pending implementation plan
**Revision:** v2 — see "Review record" at the end for what changed and why.

## Goal

A FreeCAD addon that threads any cylindrical feature. The user selects a
circular profile on an existing solid, sets direction, internal/external mode
and thread parameters, and gets a threaded part. The tool appears in the **Part
workbench** and performs the cut with a **Part boolean against a generated
thread negative**. The default diameter is derived from the diameter of the
selected circular profile.

## Environment (verified, not assumed)

| Fact | Value |
|---|---|
| FreeCAD | 1.1.1, build 44874 (Git) |
| Runs as | flatpak `org.freecad.FreeCAD`; no system `freecad`, no importable `FreeCAD` module |
| Headless | `flatpak run --command=freecadcmd org.freecad.FreeCAD script.py` |
| Addon dir | `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/` |
| Addons present | `Curves` only |
| `Gui.addWorkbenchManipulator()` | **present**; `modifyMenuBar` used for real by the bundled BIM workbench |
| `modifyToolBars` | hook exists in `libFreeCADGui.so`, but **no precedent in this build** and the toolbar name must be verified in the GUI |
| `App.newDocument(hidden=True)` | **works**; a `Shape.copy()` taken from it **survives `closeDocument()`** |
| `PartDesign::AdditiveHelix` as a Body's **base feature** | **works** — no prior solid needed; the Body's shape is the swept solid itself |
| `Part.makeThread(...)` | exists but unusable — no angle, clearance or profile control |
| `Part.BRepOffsetAPI.MakePipeShell` over `makeLongHelix` | **rejected** — distorts the profile in every mode tested (see below) |

The flatpak sandbox cannot read `/tmp/claude-*`. All scripts and outputs must
live under `/home/alexander`.

## Key insight

**Tap and die are the same operation.** Both are a helical groove *cut* into a
plain cylindrical surface — internal cuts outward from the bore, external cuts
inward from the OD. One cutter generator with a mirrored radial direction covers
both modes. This mirrors the finding in the sibling `printed_threads/` project.

## Architecture

A **cutter object plus a native `Part::Cut`**.

```
TREE
  Cut
   |- Cylinder            the user's original part
   `- ThreadCutter        our FeaturePython solid
```

Rationale: our code only ever has to produce one correct solid. The boolean is
FreeCAD's own, so we neither own nor debug it. The cutter stays visible,
inspectable and reusable, and suppressing the `Cut` shows the part unthreaded.

Rejected: *one feature owning the boolean* (we would own the helical boolean's
failure modes, and the cutter would not be inspectable); *one-shot destructive*
(no parameter editing afterwards).

### Package layout

```
FreeCADTapDie/
├── package.xml            Addon Manager metadata
├── InitGui.py             registers the command + injects it into Part
├── tapdie/
│   ├── form.py            profile maths — pure python, no FreeCAD import
│   ├── presets.py         ISO coarse-pitch table + diameter lookup
│   ├── cutter.py          profile -> Part.Shape, via a hidden-document Body
│   ├── measure.py         section-based profile measurement (the real guard)
│   ├── feature.py         ThreadCutter FeaturePython + ViewProvider
│   ├── selection.py       selection -> axis, centre, radius, internal/external
│   ├── api.py             create_thread(doc, base, ref, params) — no Gui import
│   └── command.py         thin Gui shell: task panel -> api.create_thread
├── resources/icons/
└── tests/
```

**The split that matters:** `command.py` holds only task-panel wiring. All real
work lives in `api.create_thread(...)`, which never imports `FreeCADGui`. That
is what makes steps 1–4 of the build order testable under `freecadcmd`.

### Reaching the Part workbench

`Gui.addWorkbenchManipulator()` — no fork of Part, no custom workbench. Menu
injection follows the BIM precedent. **The toolbar name is unverified**: the
literal `"Part tools"` does not appear in `PartGui.so`, so the correct target
must be found by inspection in a running GUI before step 5 is called done.
Shipping menu-only is an acceptable fallback.

## The cutter

`form.py` returns profile corners as pure data. Two rules carry over from
`printed_threads/`, both of which cost a debugging cycle there:

- Offsetting a V by a normal clearance `c` moves its apex **radially by
  `c · sec(angle/2)`**, not by `c`. Using `c` produces a self-crossing profile.
- The cutter runs **parallel to the axis** once past its shoulder, so it clears
  the crest without the swept solid ever exceeding one pitch in width. A plain
  triangle would have to be exactly one pitch wide at the crest radius, which is
  the tangency case where consecutive turns of the sweep touch.

Each form supplies `depth_internal(pitch)` and `depth_external(pitch)`:

| Form | internal | external |
|---|---|---|
| Printed 90° | `P/2` | `P/2` |
| ISO metric 60° | `0.5413 P` (5H/8) | `0.6134 P` (17H/24) |

with `H = P · √3 / 2`. Both ISO constants verified correct against ISO 68-1.

### How the sweep is actually performed

`cutter.py` builds the cutter in a **hidden scratch document**:

1. `App.newDocument(name, hidden=True)`
2. one `PartDesign::Body`, one `Sketcher::SketchObject` on XZ carrying the
   profile polygon, one `PartDesign::AdditiveHelix` **as the Body's base
   feature**
3. `recompute()`, then `body.Shape.copy()`
4. `App.closeDocument()` — the copied shape survives

The FeaturePython `ThreadCutter` then just assigns that shape. Nothing
PartDesign-related is ever created in the user's document, so there is no
recompute reentrancy and no residue in their tree.

**Measured, on the exact 6-corner truncated-V profile used by
`printed_threads/`:** volume 1799.538 mm³, valid, one solid, flank angle
**45.0000°**, tip land 0.0800 mm at r 7.9703, parallel section 3.7200 mm at
r 10.8303 — every figure exactly as designed.

**Why not `MakePipeShell`.** The original design swept the profile with
`Part.BRepOffsetAPI.MakePipeShell` over `Part.makeLongHelix`, on the mistaken
belief that `PartDesign::SubtractiveHelix` needs an active PartDesign
*workbench*. It does not — it needs a Body, which is just a document object type
available headlessly. The pipe-shell route was tested across 12 configurations
(90°/60° × coarse/fine pitch × Frenet / CorrectedFrenet / auxiliary spine) and
**distorted the profile in every one**: flank angles came out 38.13°–60.00°
where 45° or 30° was wanted, with radii off by up to 1.1 mm — an order of
magnitude beyond the 0.12–0.24 mm clearance budget. Tightening tolerance,
forcing `WithCorrection`, and substituting an exact single-edge `makeHelix`
spine all failed to fix it.

**Cost:** every `ThreadCutter.execute()` spins up a document and a PartDesign
recompute. FeaturePython only executes when touched, so this is once per
parameter edit rather than continuous, but the per-rebuild latency must be
measured in step 1 and reported. If it proves intolerable, the fallback is to
cache the shape against a hash of the parameters.

## Selection and defaults

Accept a **circular edge** or a **cylindrical face**; both yield centre, axis and
radius.

### Internal vs external detection

Probe `Shape.isInside()` just inside and just outside the circle, in the
circle's own plane. **`checkFace=True` is required** — with the default, a
circle lying on a flat end face reads `False/False` and gives no signal at all.

There are four outcomes, not two, and all four must be handled:

| inside / outside | meaning | action |
|---|---|---|
| `False` / `True` | bore | internal |
| `True` / `False` | shaft | external |
| `True` / `True` | counterbore step, or probe landed in unrelated bulk | ask the user; do not guess |
| `False` / `False` | probe epsilon exceeded the wall thickness | retry with smaller epsilon, then ask |

The probe epsilon must be **scaled to local wall thickness**, not a fixed
constant. Thin printed walls sit near the 0.4 mm extrusion floor, squarely in
the range where a fixed epsilon overshoots.

### Diameter defaults

| Mode | Selection is | Default nominal diameter |
|---|---|---|
| External (die) | shaft OD = major diameter | `detected` |
| Internal (tap) | bore ≈ tap-drill diameter | nearest table entry, see below |

**The internal lookup must search the table, not the raw diameter.** Choosing
the ISO entry whose *nominal* diameter is nearest the detected bore picks the
wrong size on every entry from M3 to M24 — a 6.8 mm hole is 0.2 mm from M7 but
1.2 mm from M8, so nearest-nominal proposes M7 × 1.0 instead of M8 × 1.25.

Instead, over all table entries `(D, P)`, minimise
`| detected − (D − 2 · depth_internal(P)) |` and take the best `D`.

Even then the match is approximate: standard tap drills target roughly 75%
thread engagement rather than the full theoretical minor diameter, so the
reconstruction lands within about −0.34 mm to +0.21 mm across the table. The
result is therefore a **starting guess the user confirms**, snapped to the
nearest preset — not an exact relationship, and the documentation must not claim
it is one.

Length defaults to the selected face's axial extent, or the solid's extent along
the axis when an edge was selected.

## Properties

`Mode`, `ThreadForm`, `Diameter`, `Pitch`, `Angle`, `Truncation`, `Clearance`,
`Length`, `Reversed`, `LeftHanded`, `LeadIn`.

`ThreadForm` is an enum: `Printed 90°` (default), `ISO metric 60°`, `Custom`.
Choosing a preset sets angle and truncation and makes them read-only; `Custom`
unlocks them.

`Reversed` flips which way along the axis the thread runs from the selected
circle. `LeftHanded` flips handedness.

### Placement binding

`ThreadCutter.Placement` **must be bound to the base part**, by attachment to
the originally selected edge/face or by expression. This is not optional:
`Part::Cut` keeps `Base` and `Tool` as independent top-level objects with
independent placements, so moving the base leaves the cutter behind and the
thread silently disappears — verified, the `Cut` recomputes to the full uncut
volume and reports success.

### Stated simplification

The ISO preset implements the **basic profile** with standard H/8 and H/4
truncations, **not tolerance classes** (6H/6g). Fit comes from the explicit
`Clearance` parameter instead. Real 6g allowance is a fixed offset unrelated to
print shrinkage, so an explicit number is more useful for printed parts — but
this will not produce a certified ISO fit, and the documentation must say so.

## Failure handling

1. **A valid solid is not a correct solid.** Every pipe-shell variant tested
   returned `isValid() == True` and `len(Solids) == 1` while carrying the wrong
   flank angle. A validity-and-solid-count guard would have passed all of them.
   `measure.py` therefore sections the generated cutter with `Shape.section()`
   against an explicit plane face and asserts the **flank angle and land widths
   against the requested parameters**. That is the real guard; validity is only
   a precondition.
2. **Cutter self-intersection.** If the profile width reaches the pitch,
   `form.py` raises and the feature enters its error state.
3. **Invalid-but-plausible boolean.** `Part::Cut` is FreeCAD's and cannot be
   guarded from inside, so `api.create_thread` recomputes and inspects the
   result, reporting loudly if it is not a single valid solid.
4. **Cutter must overrun both ends**, or a collar of plain bore is left for the
   mating crest to jam against.
5. **Lead-in ordering.** A thread cut straight to the face leaves a sharp,
   fragile, hard-to-start first turn. `printed_threads/` solves this with a 45°
   lead-in cut **before** the thread, because coning a plain cylinder is trivial
   while coning a threaded one makes OCC return an invalid solid. The `LeadIn`
   property adds the same relief, and `api.create_thread` must order it the same
   way.
6. **Stale cutter when the addon is absent.** FreeCAD 1.1 blocks the Proxy
   import on restore, leaving `Proxy = None` with the cached shape intact. The
   document opens correctly, but any later `recompute()` returns success while
   silently keeping the stale shape. Detect `Proxy is None` on a restored
   `ThreadCutter` and warn.
7. **60° overhang warning** when the ISO preset is selected — it cannot be
   printed unsupported.

Cutter creation and the boolean must be wrapped in a **single undo
transaction**, so one Ctrl-Z removes both objects rather than leaving an orphan.

## Testing

Three tiers, mirroring the pattern that works in `printed_threads/`:

- `test_form.py` — pure maths under plain `python3`, no FreeCAD. Fast.
- `test_cutter.py` — headless `freecadcmd`. Matrix over internal/external ×
  printed/ISO × diameters and pitches. Asserts a single valid solid **and
  measures the profile**, per failure-handling rule 1.
- `test_integration.py` — cylinder in, threaded solid out. Asserts the `Cut` is
  one valid solid, ray-probes a mating part for clearance, and includes a
  **move-the-base regression test** for the placement binding.

### Measurement rules inherited from this environment

Not optional; each caused a wrong passing or failing result in the sibling
project:

| API | Behaviour |
|---|---|
| `Shape.common()` | returns negative volumes, or no solids, on near-tangent helical faces |
| `Shape.BoundBox` | bounds the underlying surfaces, not the trimmed solid — use `optimalBoundingBox()` |
| `Shape.distToShape()` | misses the face-to-face minimum between coaxial bands |
| `Shape.slice()` | returns **zero wires** at the plane through the axis — use `Shape.section()` against an explicit plane face |
| ray probes | inherit `common()`'s unreliability: one probe in 86 returned material past the crest radius. Bound-check every result and count rejections |

## Build order

1. **Cutter harness.** Hidden-document Body + base `AdditiveHelix`, across the
   parameter matrix, with profile measurement. Measure and report rebuild
   latency. *(The core mechanism is already proven; this step generalises it and
   establishes the cost.)*
2. `form.py` + `presets.py` + `measure.py` + unit tests.
3. `cutter.py` + `feature.py` — a parametric ThreadCutter creatable from the
   Python console, including placement binding.
4. `selection.py` + `api.py` + integration tests — full path, still headless,
   including the four-outcome detection and the move-the-base regression.
5. `command.py` + `InitGui.py` + icons — GUI last, over proven code. Resolve the
   toolbar name here; ship menu-only if it cannot be determined.

Steps 1–4 are testable under `freecadcmd`. Only step 5 requires the GUI.

## Out of scope

- Tolerance classes and fit grades (6H/6g and friends).
- Multi-start threads.
- Tapered (NPT) threads.
- Threading non-cylindrical or non-circular features.
- Modifying the `printed_threads/` project, which stays as it is.

## Review record

Reviewed 2026-08-02 by an independent agent that ran empirical tests rather than
reading only, validating its measurement method against the known-good
`printed_threads/` bolt first (recovered 45.0000°, 9.8303, 7.9703 — matching the
README to four decimals).

Findings adopted:

| Severity | Finding | Resolution |
|---|---|---|
| Blocker | `MakePipeShell` distorts the profile in all 12 tested configurations | Replaced with hidden-document Body + base `AdditiveHelix`, measured exact |
| Blocker | Nearest-nominal-diameter lookup picks the wrong ISO size on every entry M3–M24 | Lookup restated as a search minimising reconstruction error; result is a confirmed guess, not an exact relationship |
| Blocker | `Part::Cut` does not bind Base and Tool placements; moving the part silently un-threads it | `ThreadCutter.Placement` bound to the base; regression test added |
| Significant | `isInside()` needs `checkFace=True` and has four outcomes, not two | Detection table and epsilon-scaling rule added |
| Significant | `"Part tools"` toolbar name does not exist in `PartGui.so` | Marked unverified; menu-only fallback |
| Significant | Addon-absent recompute silently keeps a stale shape | Detect `Proxy is None` and warn |
| — | Lead-in ordering, blind/through holes, undo grouping unaddressed | Added as failure-handling rules 5 and the undo-transaction requirement |

Confirmed sound under scrutiny: the ISO depth constants (5H/8, 17H/24);
`isInside()` on unambiguous shaft and bore cases; `addWorkbenchManipulator` /
`modifyMenuBar`; documents opening safely without the addon installed.

Two review conclusions were checked independently and refined:

- The reviewer proposed building scratch PartDesign objects in the **user's**
  document and deleting them afterwards. Building in a **hidden document**
  instead was verified to work and avoids recompute reentrancy inside
  `execute()`.
- The reviewer's fix implied a Body plus a subtractive feature. An
  `AdditiveHelix` as the Body's **base feature** was verified to work directly,
  making the Body's shape the cutter itself — simpler, with nothing to infer.
