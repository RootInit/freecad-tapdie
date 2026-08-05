# Changelog

All notable changes to this addon. Dates are ISO; versions follow
[semantic versioning](https://semver.org/).

## [0.2.0] — 2026-08-04

The first release worth installing. 0.1.x cut threads, but several of its
settings did not do what they said, and a few did nothing at all.

### Added

- **Diameter drives the size.** It used to be passed to the profile maths and
  never read — byte-identical profiles for 8.0 and 24.0 — so a user threading
  a Ø20 shaft could ask for 16 and silently get 20. The cutter now reaches
  further to reach the size asked for.
- **Material is added when cutting alone cannot reach the size** — a sleeve
  around a shaft, a liner inside a bore — so an M12 thread goes on an 8 mm
  shaft. Only when needed, and never for a shortfall under one extrusion
  width, which no printer would resolve.
- **Start angle**, for lining a thread up with something else. An internal
  thread is automatically clocked half a pitch from an external one, so a nut
  and bolt cut with the same settings mate as they stand.
- **Flat circular faces are selectable** — the disc at the end of a rod is a
  far bigger target than the edge around it.
- **A simple/advanced split** in the dialog. Seven settings are enough to cut
  a thread; the rest were burying them.
- **Overrun** and the **Custom** form's angle and land widths are now
  editable. Custom was previously a dead end: it froze the last preset's
  values with no way to change them.
- ISO coarse table extended to M100, with sizes past it taken from the
  selection instead of snapped back to the largest entry.

### Fixed

- **The flats had zero clearance.** A mated pair touched exactly at every
  crest and root — the flank offset and the bore sizing cancelled — so a
  crest bottomed out before the flanks ever met. Both gaps now follow from
  one setting.
- **One Ctrl-Z removes the whole thread** and gives the part back. It used to
  strand the boolean with its tool gone *and* leave the base hidden. The
  cause was the sweep's scratch document being created and closed inside a
  recompute, which destroys the caller's transaction.
- **A fillet was threadable** — it is a cylindrical face, so a mis-click on a
  rounded corner cut a helix around mostly empty air.
- **Lead-in chamfers gouged an abutting end** on a short run.
- **A failed preview stranded an invalid cutter** in the tree when the
  settings were corrected and applied.
- Errors now report what actually went wrong instead of a fixed guess.
- A zero surface radius or diameter is refused rather than quietly building
  something unrelated to the input.
- The printed 90° form is near-triangular again; an extrusion-width floor on
  its lands had been eating the thread depth it was meant to protect.

### Changed

- Clearance is a single setting. There were briefly two, and the flank one
  did nothing measurable at all.

## [0.1.0] — 2026-08-02

First working version: helical cutter, internal and external, ISO 60° and
printed 90° forms, live preview, free/abutting end detection.
