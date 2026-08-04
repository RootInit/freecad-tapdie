"""Entry point for the FreeCAD-dependent tests.

freecadcmd executes a script, not a test runner, so unittest is driven by
hand.  Exits non-zero on failure so run_tests.sh propagates the result.
"""

import os
import sys
import unittest
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "FreeCADTapDie"))
sys.path.insert(0, ROOT)

MODULES = ["tests.test_cutter", "tests.test_selection", "tests.test_integration",
           "tests.test_profile_shape"]

suite = unittest.TestSuite()
loader = unittest.TestLoader()
for name in MODULES:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, AttributeError, ValueError):
        spec = None
    if spec is None:
        print("  (skipping %s -- not written yet)" % name, flush=True)
        continue
    suite.addTests(loader.loadTestsFromName(name))

result = unittest.TextTestRunner(verbosity=2).run(suite)
print("FC TESTS: %d run, %d failures, %d errors"
      % (result.testsRun, len(result.failures), len(result.errors)), flush=True)
if not result.wasSuccessful():
    raise SystemExit(1)
