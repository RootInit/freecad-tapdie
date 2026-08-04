"""What does FreeCAD actually do with transactions here?

Four candidate shapes for the preview's lifecycle, measured rather than
assumed. For each: does Cancel leave the document clean, and what does it
leave on the undo stack for the user's next Ctrl-Z to hit?
"""

import os
import sys

import FreeCAD as App

LOG = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "diag_undo.log"), "w")


def line(msg):
    LOG.write("%s\n" % msg)
    LOG.flush()


def fresh():
    doc = App.newDocument("u", hidden=False)
    App.setActiveDocument(doc.Name)
    a = doc.addObject("Part::Box", "Keep")
    doc.recompute()
    return doc, {o.Name for o in doc.Objects}


def make(doc):
    """Two linked objects plus a recompute -- the shape of build_thread."""
    box = doc.addObject("Part::Box", "Tool")
    doc.recompute()
    cut = doc.addObject("Part::Cut", "Result")
    cut.Base = doc.getObject("Keep")
    cut.Tool = box
    doc.recompute()
    return [box, cut]


def report(label, doc, baseline):
    doc.recompute()
    left = sorted({o.Name for o in doc.Objects} - baseline)
    line("%-34s left=%-28s undo=%s" % (label, left or "clean", doc.UndoNames))
    App.closeDocument(doc.Name)


# A: transaction, abort only
doc, base = fresh()
doc.openTransaction("Thread")
make(doc)
doc.abortTransaction()
report("A abort only", doc, base)

# B: transaction, abort then remove
doc, base = fresh()
doc.openTransaction("Thread")
objs = make(doc)
doc.abortTransaction()
for o in reversed(objs):
    try:
        doc.removeObject(o.Name)
    except Exception:
        pass
report("B abort then remove", doc, base)

# C: transaction, remove then abort
doc, base = fresh()
doc.openTransaction("Thread")
objs = make(doc)
for o in reversed(objs):
    try:
        doc.removeObject(o.Name)
    except Exception:
        pass
doc.abortTransaction()
report("C remove then abort", doc, base)

# D: no transaction at all, just remove
doc, base = fresh()
objs = make(doc)
for o in reversed(objs):
    try:
        doc.removeObject(o.Name)
    except Exception:
        pass
report("D no transaction, remove", doc, base)

# E: what a COMMITTED transaction costs in undo steps
doc, base = fresh()
doc.openTransaction("Thread")
make(doc)
doc.commitTransaction()
doc.recompute()
line("E committed: undo=%s" % (doc.UndoNames,))
doc.undo()
doc.recompute()
line("%-34s after 1 undo left=%s"
     % ("E commit + undo", sorted({o.Name for o in doc.Objects} - base)))
App.closeDocument(doc.Name)


# F: does a Part::FeaturePython with a Proxy behave differently under undo?
# That is the one structural difference between this fixture and the real
# ThreadCutter, so it is the candidate explanation for the leftover Cut.
class Proxy(object):
    def execute(self, obj):
        import Part
        obj.Shape = Part.makeBox(1, 1, 1)


doc, base = fresh()
doc.openTransaction("Thread")
tool = doc.addObject("Part::FeaturePython", "PyTool")
Proxy(); tool.Proxy = Proxy()
doc.recompute()
cut = doc.addObject("Part::Cut", "Result")
cut.Base, cut.Tool = doc.getObject("Keep"), tool
doc.recompute()
doc.commitTransaction()
line("F featurepython committed: undo=%s" % (doc.UndoNames,))
doc.undo()
doc.recompute()
line("%-34s after 1 undo left=%s"
     % ("F featurepython + undo", sorted({o.Name for o in doc.Objects} - base)))
App.closeDocument(doc.Name)


# G: the real thing. Does one undo clear a thread made by api.create_thread
# -- the one-shot path, untouched by the preview work? If not, the leftover
# Part::Cut is a pre-existing property of the design (the cutter links to the
# base AND the Cut consumes both, a diamond), not something the preview
# introduced.
sys.path.insert(0, "/home/alexander/Documents/CAD/freecad_tapdie/FreeCADTapDie")
from tapdie import api   # noqa: E402

doc = App.newDocument("real")
App.setActiveDocument(doc.Name)
shaft = doc.addObject("Part::Cylinder", "Shaft")
shaft.Radius, shaft.Height = 4.0, 30.0
doc.recompute()
sub = None
for i, f in enumerate(shaft.Shape.Faces):
    if hasattr(f.Surface, "Radius") and abs(f.Surface.Radius - 4.0) < 1e-6:
        sub = "Face%d" % (i + 1)
base_names = {o.Name for o in doc.Objects}
api.create_thread(doc, shaft, sub)
doc.recompute()
line("G create_thread committed: undo=%s" % (doc.UndoNames,))
doc.undo()
doc.recompute()
line("%-34s after 1 undo left=%s"
     % ("G create_thread + undo", sorted({o.Name for o in doc.Objects} - base_names)))
App.closeDocument(doc.Name)

LOG.close()
os._exit(0)
