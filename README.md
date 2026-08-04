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

1. Select one cylindrical face, or one circular edge, on a solid.
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

### Things worth knowing

- **Direction** matters when you select an *edge*. An edge sits at one end of
  the feature, so "Both ways" would put half the run in open air. It is probed
  for automatically; a cylindrical face always straddles its own midpoint.
- **Clearance is taken radially.** The cutter relieves the blank to the crest
  radius over the threaded run and anchors the thread profile on that relieved
  surface — which is what a real die does. A bolt and a nut cut with the same
  settings end up `2 × clearance` apart on the flanks, and the crest and root
  flats come out at exactly the widths asked for at any pitch.
- **Ends that abut adjacent material are detected** (a shoulder, a hex head, a
  blind bore's floor) and faced off flat with no lead-in chamfer, so the
  sweep's overrun does not gouge into the neighbour. Free ends get a 45°
  lead-in so the first turn is not a fragile knife edge.
- **Known limitation:** one Ctrl-Z after creating a thread removes the cutter
  but leaves the `Part::Cut` behind. Delete it by hand. Measured, not
  theorised — see `tools/diag_undo.py`.

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
./run_tests.sh        # both
```

The `fc` half assumes FreeCAD is installed as the
`org.freecad.FreeCAD` flatpak; edit `FC` in `run_tests.sh` otherwise.

Diagnostics that need a GUI run offscreen and unattended:

```sh
flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD tools/diag_preview.py
```

## License

LGPL-2.1-or-later. See [LICENSE](LICENSE).
