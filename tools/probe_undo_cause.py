"""Why did one Ctrl-Z leave a broken Part::Cut behind?

ANSWER, 2026-08-04: cutter.build created AND closed a hidden scratch document
inside execute(), and doing both during a recompute destroys the undo
transaction the caller has open on a different document.

NOT the answer, though it was written down as fact in api.create_thread's
docstring and in CLAUDE.md for months: the dependency DIAMOND (the cutter
links to the base via AttachedTo while the Cut consumes both). Measured
innocent -- see F1 and G0 below. A plausible cause recorded without being
isolated stops the search, which is the whole reason this file exists.

The bisection, starting from a fixture that works and adding back one
difference at a time:

    F  Part::FeaturePython + Part::Cut, one transaction    -> clean
    F1 + the identical AttachedTo diamond                  -> clean
    F2 + proxy writes Placement during execute             -> clean
    F3 + proxy writes an output property during execute    -> clean
    F5 one recompute in the transaction instead of two     -> clean
    H1 + execute opens AND closes a hidden document        -> BROKEN
    H3 the same document churn done by the CALLER          -> clean
    I1 execute creates a document, never closes it         -> clean
    I2 execute closes a document that predates it          -> clean
    I3 execute reuses one long-lived hidden document       -> clean
    L1 create+close but with temp=True                     -> BROKEN

So it is specifically the create/close PAIR, during a recompute. The fix is
cutter._scratch_document: one document, created once, emptied between builds,
never closed.

The damage was also worse than recorded: the base part was left HIDDEN after
the undo (Part::Cut hides its Base and the undo never gave it back), so the
user was left with an empty viewport as well as a broken object.

Run after any change to cutter.build's document handling:

    flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD \\
        tools/probe_undo_cause.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "FreeCADTapDie"))

import FreeCAD as App                                        # noqa: E402
import Part                                                  # noqa: E402

LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "probe_undo_cause.log"), "w")
failures = []


def line(msg):
    LOG.write("%s\n" % msg)
    LOG.flush()


class Plain(object):
    """The control: writes only the Shape."""

    def execute(self, obj):
        obj.Shape = Part.makeBox(1, 1, 1)


class CreatesAndCloses(object):
    """What cutter.build used to do."""
    n = [0]

    def execute(self, obj):
        self.n[0] += 1
        previous = App.ActiveDocument
        scratch = App.newDocument("probe_scratch%d" % self.n[0], hidden=True)
        try:
            scratch.addObject("Part::Box", "X")
            scratch.recompute()
        finally:
            App.closeDocument(scratch.Name)
            if previous is not None:
                try:
                    App.setActiveDocument(previous.Name)
                except Exception:
                    pass
        obj.Shape = Part.makeBox(1, 1, 1)


class CreatesOnly(object):
    n = [0]

    def execute(self, obj):
        self.n[0] += 1
        App.newDocument("probe_leak%d" % self.n[0], hidden=True)
        obj.Shape = Part.makeBox(1, 1, 1)


def case(label, proxy, link_to_base=False, expect_clean=True):
    doc = App.newDocument("u%d" % case.counter)
    case.counter += 1
    App.setActiveDocument(doc.Name)
    doc.UndoMode = 1          # freecadcmd defaults this to 0: records nothing
    keep = doc.addObject("Part::Box", "Keep")
    doc.recompute()
    baseline = {o.Name for o in doc.Objects}

    doc.openTransaction("Thread")
    tool = doc.addObject("Part::FeaturePython", "PyTool")
    if link_to_base:
        tool.addProperty("App::PropertyLink", "AttachedTo", "T", "")
        tool.AttachedTo = keep
    tool.Proxy = proxy
    doc.recompute()
    cut = doc.addObject("Part::Cut", "Result")
    cut.Base, cut.Tool = keep, tool
    doc.recompute()
    doc.commitTransaction()

    doc.undo()
    doc.recompute()
    left = sorted({o.Name for o in doc.Objects} - baseline)
    clean = not left
    ok = clean == expect_clean
    line("%-52s -> %-9s %s" % (label, "clean" if clean else "BROKEN",
                               "" if ok else "  <-- UNEXPECTED"))
    if not ok:
        failures.append(label)
    App.closeDocument(doc.Name)


case.counter = 0

line("=== the diamond is innocent ===")
case("F  plain proxy, no link", Plain())
case("F1 + the AttachedTo diamond", Plain(), link_to_base=True)

line("")
line("=== the scratch document is the cause ===")
case("H1 execute creates AND closes a document", CreatesAndCloses(),
     expect_clean=False)
case("I1 execute creates one, never closes it", CreatesOnly())

line("")
line("=== the real path, with the fix in place ===")
from tapdie import api, cutter                                # noqa: E402

doc = App.newDocument("real")
App.setActiveDocument(doc.Name)
doc.UndoMode = 1
shaft = doc.addObject("Part::Cylinder", "Shaft")
shaft.Radius, shaft.Height = 4.0, 30.0
doc.recompute()
sub = None
for i, f in enumerate(shaft.Shape.Faces):
    if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - 4.0) < 1e-6:
        sub = "Face%d" % (i + 1)
baseline = {o.Name for o in doc.Objects}
api.create_thread(doc, shaft, sub)
doc.recompute()
doc.undo()
doc.recompute()
left = sorted({o.Name for o in doc.Objects} - baseline)
orphans = [n for n in left if doc.getObject(n).TypeId == "Part::Cut"
           and doc.getObject(n).Tool is None]
visible = shaft.ViewObject is None or shaft.ViewObject.Visibility
line("G  api.create_thread, one undo                        -> %s"
     % ("clean" if not left else "BROKEN, left %s" % left))
line("   orphaned Part::Cut                                 -> %s"
     % (orphans or "none"))
line("   base part visible again                            -> %s" % visible)
line("   scratch documents open                             -> %s"
     % [n for n in App.listDocuments() if n.startswith(cutter.SCRATCH)])
for label, bad in (("undo left objects behind", bool(left)),
                   ("orphaned Part::Cut", bool(orphans)),
                   ("base left hidden", not visible)):
    if bad:
        failures.append(label)
App.closeDocument(doc.Name)

line("")
line("UNDO PROBE: %d unexpected result(s)" % len(failures))
for name in failures:
    line("   FAILED: %s" % name)
LOG.close()
sys.stdout.flush()
os._exit(1 if failures else 0)
