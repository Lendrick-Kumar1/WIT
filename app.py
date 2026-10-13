"""WIT: CLO trustee reports -> Balance, Performance, Collateral (Excel).

    WIT.exe / python app.py              opens the window
    python app.py run --months 2026-08   command line (python app.py run -h for all options)
    python app.py inspect <pdf> --pages 12
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from wit.cli import main
        sys.exit(main())
    from wit.gui import main
    main()
