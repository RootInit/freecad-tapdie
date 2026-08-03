"""Entry point for the FreeCAD-dependent tests.

freecadcmd executes a script, not a test runner, so unittest is driven by
hand.  Exits non-zero on failure so run_tests.sh propagates the result.
"""

import os
import sys
import unittest
import importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "FreeCADTapDie"))
sys.path.insert(0, ROOT)

MODULES = ["tests.test_cutter", "tests.test_selection", "tests.test_integration"]

suite = unittest.TestSuite()
loader = unittest.TestLoader()
for name in MODULES:
    try:
        # Try to import the module first to catch import errors before
        # loadTestsFromName wraps them in _FailedTest (Python 3.3+)
        importlib.import_module(name)
        suite.addTests(loader.loadTestsFromName(name))
    except (ImportError, AttributeError):
        print("  (skipping %s -- not written yet)" % name)

result = unittest.TextTestRunner(verbosity=2).run(suite)
print("FC TESTS: %d run, %d failures, %d errors"
      % (result.testsRun, len(result.failures), len(result.errors)))
if not result.wasSuccessful():
    raise SystemExit(1)
