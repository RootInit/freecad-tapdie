# freecad-tapdie

A FreeCAD addon that cuts a real helical thread into a cylinder you already
have — pick a cylindrical face or a circular edge, set the size, and it
removes the material a tap or a die would.

It is aimed at **FDM printing**. The default form is a 90° included angle,
which puts every flank at exactly the 45° overhang limit; standard ISO 60° is
available but droops when printed axis-vertical.

Status: 0.1.0, works, tested headlessly and through an offscreen GUI. Not yet
listed in the FreeCAD Addon Manager.

## Install

Clone (or symlink) `FreeCADTapDie/` into your FreeCAD Mod directory:

```sh
git clone https://github.com/RootInit/freecad-tapdie
ln -s "$PWD/freecad-tapdie/FreeCADTapDie" ~/.FreeCAD/Mod/TapDie
```

Flatpak users want
`~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/` instead. Restart
FreeCAD; **Tap / Die...** appears in the Part workbench's menu and toolbar.

## Use

1. Select one cylindrical face, one **flat circular face** (the end of a rod
   is a much bigger target than the edge around it), or one circular edge.
2. Run **Part → Tap / Die...**
3. Internal vs external is detected by probing the material either side of the
   circle; the dialog says so when it could not tell.
4. Set diameter, pitch, length, clearance, then press **Refresh preview**. The
   cutter shows as a translucent red solid over the untouched part — it is
   exactly the material that will be removed.
5. **OK** performs the boolean as a native `Part::Cut`.

The cutter stays in the tree as a parametric `ThreadCutter`, linked to the base
part, so editing its properties re-cuts the thread and moving the part carries
the thread with it.

The dialog opens **simple** — Mode, Form, Diameter, Pitch, Length, Direction
and Clearance, which is all it takes to cut a thread. **Show advanced
settings** adds the angle and land widths, overrun, start angle, flush ends,
handedness, and whether material may be added.

### Things worth knowing

- **Direction** matters when you select an *edge*. An edge sits at one end of
  the feature, so "Both ways" would put half the run in open air. It is probed
  for automatically; a cylindrical face always straddles its own midpoint.
- **One clearance, because it can only be one.** Both profiles are the same V
  displaced radially, and a radial displacement has a single degree of
  freedom: it fixes the flank gap and the flat gap together. A bolt and nut
  cut with the same settings end up `2 × Clearance` apart normal to the
  **flanks**, and wider at the **flats** by `1/sin(angle/2)` — 2.83× the
  clearance at 90°, which is the right way round, since a crest is the least
  accurate feature an FDM machine makes. There were briefly two settings and
  the flank one did nothing at all; `tools/probe_mated_gap.py` measures the
  real numbers rather than restating the promise.
- **The printed 90° form is near-triangular.** Its lands are 0.021 × pitch —
  0.026 mm at M8×1.25 — just enough to avoid a mathematically sharp tip, which
  is the tangency case where consecutive turns of the sweep touch. Everything
  else in the pitch budget goes to depth.
- **Start angle** sets where the thread begins around the axis, for lining a
  thread up with something else. An internal thread is already clocked half a
  pitch (180°) from an external one, so a nut and bolt cut with the same
  settings mate as they stand.
- **Ends that abut adjacent material are detected** (a shoulder, a hex head, a
  blind bore's floor) and faced off flat with no lead-in chamfer, so the
  sweep's overrun does not gouge into the neighbour. Free ends get a 45°
  lead-in so the first turn is not a fragile knife edge.
- **Diameter drives the size**, and the cutter reaches further to reach it: a
  die turns the shaft down as it cuts, a tap opens the bore out. So you can
  ask for an M16 thread on a Ø20 shaft, or an M20 thread in a Ø10 bore, and
  get it. Only one direction is available in each mode, because cutting
  removes material and cannot add it — external can go *smaller* than the
  shaft, internal *larger* than the bore.
- **Add material if needed** (on by default, advanced) covers the other
  direction: when the diameter you asked for cannot be cut from the blank, a
  tube is fused on first — a sleeve around the shaft, or a liner inside the
  bore — and then the ordinary cutter works on the result. So an M12 thread
  will happily go on an 8 mm shaft. Nothing is added when cutting alone can
  reach the size, and the dialog tells you before OK does it. Turn it off and
  those cases fall back to the blank and say so instead.
- **Form → Custom** unlocks the included angle and both land widths. On a
  preset they are computed from form, pitch and mode, and shown greyed.
- **One Ctrl-Z removes the whole thread** — the cutter and the boolean — and
  gives you the original part back. This was not always so: it used to strand
  the `Part::Cut` with its Tool gone *and* leave the base hidden. The cause
  was `cutter.build` creating and closing its scratch document inside
  `execute()`, which destroys the caller's open transaction. See
  `tools/probe_undo_cause.py` for the bisection.

## Layout

| | |
|---|---|
| `FreeCADTapDie/tapdie/form.py` | Cutter profile mathematics. Pure Python, no FreeCAD import. |
| `FreeCADTapDie/tapdie/presets.py` | ISO coarse table and the diameter lookups. Also pure. |
| `FreeCADTapDie/tapdie/cutter.py` | Sweeps the profile via a `PartDesign::AdditiveHelix` in a hidden document. |
| `FreeCADTapDie/tapdie/feature.py` | The parametric `ThreadCutter` object. |
| `FreeCADTapDie/tapdie/selection.py` | Selection → axis, radius, mode, direction. |
| `FreeCADTapDie/tapdie/api.py` | Orchestration. Never imports `FreeCADGui`. |
| `FreeCADTapDie/tapdie/command.py` | The Gui command and task panel. The only module that may import `FreeCADGui`. |
| `tools/` | Probes and offscreen-GUI diagnostics kept from the build. |

`docs/` carries the design spec and the implementation plan.

## Tests

```sh
./run_tests.sh pure   # profile maths and packaging; no FreeCAD needed
./run_tests.sh fc     # geometry tests inside the flatpak
./run_tests.sh diag   # the task panel, in an offscreen GUI
./run_tests.sh        # all three
```

The `fc` and `diag` halves assume FreeCAD is installed as the
`org.freecad.FreeCAD` flatpak; edit `FC` in `run_tests.sh` otherwise.

`diag` matters more than its size suggests: `freecadcmd` never runs
`InitGui.py` and has no `FreeCADGui`, so command registration, the task panel,
its undo transaction and the enabled state of a control are invisible to
everything else. It has caught a preview showing stale geometry, a Cancel path
that stranded objects, a cutter orphaned by a failed-then-corrected preview,
and a set of controls that never enabled.

`tools/` also holds standalone probes, each documenting the number it measured:

```sh
python3 tools/probe_diameter.py                              # no FreeCAD needed
flatpak run --command=freecadcmd org.freecad.FreeCAD tools/probe_chamfer_overreach.py
```

## License

LGPL-2.1-or-later. See [LICENSE](LICENSE).
