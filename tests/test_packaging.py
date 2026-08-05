"""Guards the three ways this addon has silently failed to load.

None of these are code bugs in the usual sense -- every one of them left a
FreeCAD that started cleanly, reported nothing in the Report view, and simply
had no Tap / Die command.  Each cost a live GUI round trip to find, so each
gets a test that runs without FreeCAD at all:

  1. package.xml declaring content type <other> instead of <workbench>.
     FreeCAD 1.1 still puts the directory on sys.path -- so importing the
     package by hand in the console works, which is exactly what makes this
     so confusing -- but never executes InitGui.py.

  2. package.xml not being well-formed XML.  The parse error goes to stdout
     only.  (An XML comment containing a doubled hyphen did this.)

  3. InitGui.py relying on a module-level name from inside a function.
     FreeCAD exec()s the file with distinct globals and locals dicts, so
     top-level bindings land in locals while function bodies resolve free
     names in globals.  `def _register()` referencing a top-level class
     raised NameError at startup, reported to stdout and nowhere else.

Test 3 is the important one: it reproduces FreeCAD's two-dict exec rather
than importing the module, because a plain import would bind everything into
one namespace and pass no matter what.
"""

import os
import sys
import types
import unittest
import xml.etree.ElementTree as ET

ADDON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "FreeCADTapDie")
PACKAGE_XML = os.path.join(ADDON, "package.xml")
INIT_GUI = os.path.join(ADDON, "InitGui.py")

NS = "{https://wiki.freecad.org/Package_Metadata}"


class PackageMetadataTest(unittest.TestCase):
    def test_package_xml_is_well_formed(self):
        # ET.parse raises ParseError on the malformed case; letting it
        # propagate names the line and column, same as FreeCAD's own message.
        ET.parse(PACKAGE_XML)

    def test_the_metadata_the_addon_manager_shows_is_present(self):
        """Without these the listing has no links and no version floor.

        Pinned individually rather than as a set, so dropping one names
        itself instead of failing as "metadata is wrong somewhere".
        """
        root = ET.parse(PACKAGE_XML).getroot()
        for tag in ("name", "description", "version", "maintainer",
                    "license", "freecadmin", "icon"):
            node = root.find(NS + tag)
            self.assertIsNotNone(node, "package.xml has no <%s>" % tag)
            self.assertTrue((node.text or "").strip(),
                            "<%s> is empty" % tag)

    def test_the_repository_and_bugtracker_are_linked(self):
        root = ET.parse(PACKAGE_XML).getroot()
        urls = dict((u.get("type"), (u.text or "").strip())
                    for u in root.findall(NS + "url"))
        for kind in ("repository", "readme", "bugtracker"):
            self.assertIn(kind, urls, "package.xml has no %s url" % kind)
            self.assertTrue(urls[kind].startswith("https://"),
                            "%s url is not https: %r" % (kind, urls[kind]))
        self.assertIsNotNone(
            root.find(NS + "url[@type='repository']").get("branch"),
            "the repository url needs the branch the Addon Manager clones")

    def test_the_version_is_a_plain_three_part_number(self):
        root = ET.parse(PACKAGE_XML).getroot()
        version = root.find(NS + "version").text.strip()
        parts = version.split(".")
        self.assertEqual(len(parts), 3, "version %r is not x.y.z" % version)
        for part in parts:
            self.assertTrue(part.isdigit(),
                            "version %r has a non-numeric part" % version)

    def test_the_version_floor_is_one_we_have_actually_run_on(self):
        """1.1 is the only release this has been tested against, and a floor
        below that would be a guess presented as a promise."""
        root = ET.parse(PACKAGE_XML).getroot()
        self.assertEqual(root.find(NS + "freecadmin").text.strip(), "1.1")

    def test_the_changelog_records_this_version(self):
        root = ET.parse(PACKAGE_XML).getroot()
        version = root.find(NS + "version").text.strip()
        changelog = os.path.join(os.path.dirname(ADDON), "CHANGELOG.md")
        self.assertTrue(os.path.exists(changelog), "no CHANGELOG.md")
        with open(changelog) as handle:
            text = handle.read()
        self.assertIn("[%s]" % version, text,
                      "CHANGELOG.md does not mention version %s" % version)

    def test_content_is_declared_as_a_workbench(self):
        root = ET.parse(PACKAGE_XML).getroot()
        content = root.find(NS + "content")
        self.assertIsNotNone(content, "package.xml declares no <content>")
        kinds = [child.tag.replace(NS, "") for child in content]
        self.assertEqual(
            kinds, ["workbench"],
            "FreeCAD 1.1 executes InitGui.py only for <workbench> content; "
            "declared %s instead" % kinds)


class InitGuiExecTest(unittest.TestCase):
    """Executes InitGui.py the way FreeCAD does, against stub modules."""

    def setUp(self):
        self._saved = {name: sys.modules.get(name) for name in
                       ("FreeCAD", "FreeCADGui", "tapdie", "tapdie.command")}
        self.added = []
        self.errors = []

        gui = types.ModuleType("FreeCADGui")
        gui.addWorkbenchManipulator = self.added.append
        gui.addCommand = lambda name, obj: None

        app = types.ModuleType("FreeCAD")
        app.Console = types.SimpleNamespace(
            PrintError=self.errors.append,
            PrintMessage=lambda msg: None,
            PrintWarning=lambda msg: None)

        # Stub the package too: the real tapdie.command imports FreeCADGui
        # and PySide for real. Without this the exec would take InitGui's
        # except branch and the manipulator assertions would pass vacuously
        # on a broken build.
        pkg = types.ModuleType("tapdie")
        pkg.__path__ = [os.path.join(ADDON, "tapdie")]
        command = types.ModuleType("tapdie.command")
        pkg.command = command

        sys.modules.update({"FreeCAD": app, "FreeCADGui": gui,
                            "tapdie": pkg, "tapdie.command": command})

    def tearDown(self):
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def _exec(self):
        with open(INIT_GUI) as handle:
            source = handle.read()
        # Two dicts, not one. This is the whole point of the test: FreeCAD
        # calls exec(source, globals, locals) with separate mappings, and
        # passing a single dict here would hide the very bug being guarded.
        exec(compile(source, INIT_GUI, "exec"), {}, {})

    def test_exec_with_split_namespaces_registers_the_manipulator(self):
        self._exec()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.added), 1,
                         "InitGui.py added no workbench manipulator")

    def test_menu_descriptor_anchors_on_a_real_part_menu_item(self):
        self._exec()
        entries = self.added[0].modifyMenuBar()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["insert"], "TapDie_Thread")
        # Part_Boolean is a submenu trigger, not a top-level item; anchoring
        # there put the entry nowhere visible.
        self.assertEqual(entry["menuItem"], "Part_Fillet")

    def test_toolbar_descriptor_uses_a_display_name(self):
        self._exec()
        entries = self.added[0].modifyToolBars()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["append"], "TapDie_Thread")
        # 'Part Tools' is the toolbar's human-readable title, as dumped from
        # a live Part workbench. A command-group id like "Part_Booleans"
        # matches nothing and fails silently, so reject that whole shape.
        self.assertEqual(entry["toolBar"], "Part Tools")
        self.assertNotIn("_", entry["toolBar"])


if __name__ == "__main__":
    unittest.main()
