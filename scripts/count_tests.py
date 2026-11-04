"""Prints the real test total by running the suite."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parents[1] / "tests"))
result = unittest.TextTestRunner(verbosity=0).run(suite)
print(f"TOTAL_TESTS={result.testsRun} FAILURES={len(result.failures)} ERRORS={len(result.errors)}")
sys.exit(0 if result.wasSuccessful() else 1)
