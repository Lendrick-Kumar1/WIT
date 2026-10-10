"""Run every test_*() in tests/test_*.py without needing pytest:

    poetry run python tests/run_tests.py            (pytest works too, if installed)
"""
import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

failed = passed = 0
for f in sorted(HERE.glob("test_*.py")):
    mod = importlib.import_module(f.stem)
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, name)()
            passed += 1
        except Exception:
            failed += 1
            print(f"FAIL  {f.stem}.{name}")
            traceback.print_exc(limit=3)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
