"""Does building a cutter steal the active document?

cutter.build() creates a hidden scratch document for the PartDesign helix and
closes it again. If newDocument() makes that scratch the ACTIVE document, then
closing it leaves App.ActiveDocument pointing at nothing -- and every FreeCAD
GUI command that operates on "the active document" (add an object, delete an
object) silently does nothing from then on.

That would explain both the reported "cannot delete or add anything after
generating a thread" AND the None ActiveDocument that made the task panel's
Cancel raise.
"""

import os
import sys

import FreeCAD as App

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "FreeCADTapDie"))

from tapdie import api, cutter, form  # noqa: E402


def name_of(doc):
    return doc.Name if doc is not None else "<None>"


doc = App.newDocument("work")
App.setActiveDocument(doc.Name)
print("active before          : %s" % name_of(App.ActiveDocument))
print("open documents before  : %s" % sorted(App.listDocuments()))

points = form.cutter_points(form.EXTERNAL, form.PRINTED, 8.0, 1.25, 90.0,
                            0.225, 0.225, 0.12, 4.0, 1.0)
cutter.build(points, 1.25, 10.0)

print("active after build     : %s" % name_of(App.ActiveDocument))
print("open documents after   : %s" % sorted(App.listDocuments()))

shaft = doc.addObject("Part::Cylinder", "Shaft")
shaft.Radius, shaft.Height = 4.0, 30.0
doc.recompute()
sub = None
for i, face in enumerate(shaft.Shape.Faces):
    if hasattr(face.Surface, "Radius") and abs(face.Surface.Radius - 4.0) < 1e-6:
        sub = "Face%d" % (i + 1)
App.setActiveDocument(doc.Name)
print("active before thread   : %s" % name_of(App.ActiveDocument))
api.create_thread(doc, shaft, sub, {"Mode": form.EXTERNAL, "Diameter": 8.0,
                                    "Pitch": 1.25, "Length": 12.0})
print("active after thread    : %s" % name_of(App.ActiveDocument))
print("open documents at end  : %s" % sorted(App.listDocuments()))

ok = App.ActiveDocument is not None and App.ActiveDocument.Name == doc.Name
print()
print("VERDICT: %s" % ("active document preserved"
                       if ok else "ACTIVE DOCUMENT LOST -- this is the bug"))
