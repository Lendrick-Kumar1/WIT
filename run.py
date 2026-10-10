"""Entry point:  poetry run python run.py reports/*.pdf      (outputs in out/)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from wit.run import main  # noqa: E402

if __name__ == "__main__":
    main()
