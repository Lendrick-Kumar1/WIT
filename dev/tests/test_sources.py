"""sources: month folders, PDF checks, duplicates, missing months (temporary folders, tiny PDFs)."""
import os
import tempfile
import time
from pathlib import Path

import helpers  # noqa: F401  (puts src/ on the path)
import pymupdf

from wit.sources import check_pdf, find_report, month_of, months_between

TYPES = ["Monthly Trustee Report", "Quarterly Trustee Report"]


def make_pdf(path, text="Trustee report"):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(str(path))
    return path


def test_month_of_folder_and_file_names():
    assert month_of("2026_08") == (2026, 8)
    assert month_of("2026-8") == (2026, 8)
    assert month_of("202608") == (2026, 8)
    assert month_of("2026_08_15") == (2026, 8)
    assert month_of("Deal 2019-1 2026_08") == (2026, 8)       # the last month in the name counts
    assert month_of("Trustee Report") is None and month_of("2026_13") is None


def test_months_between():
    assert months_between("2025-11", "2026-02") == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


def test_check_pdf_finds_broken_files():
    with tempfile.TemporaryDirectory() as d:
        good = make_pdf(Path(d) / "good.pdf")
        assert check_pdf(good) == "ok"
        (Path(d) / "empty.pdf").write_bytes(b"")
        assert check_pdf(Path(d) / "empty.pdf") == "empty file"
        (Path(d) / "junk.pdf").write_bytes(b"<html>not a pdf</html>")
        assert check_pdf(Path(d) / "junk.pdf").startswith("not a PDF")
        data = good.read_bytes()
        (Path(d) / "cut.pdf").write_bytes(data[: len(data) // 2])
        assert check_pdf(Path(d) / "cut.pdf").startswith("damaged")


def test_find_report_priority_duplicates_and_missing():
    with tempfile.TemporaryDirectory() as d:
        s = {"reports_root": d, "report_types": TYPES}
        make_pdf(Path(d) / "Deal A" / "Quarterly Trustee Report" / "2026_08" / "q.pdf")
        make_pdf(Path(d) / "Deal A" / "Monthly Trustee Report" / "2026_08" / "m.pdf")
        r = find_report(s, "Deal A", (2026, 8))
        assert r["report_type"] == "Monthly Trustee Report" and r["file_status"] == "ok"   # priority

        # identical copy -> fine, plain name used; a different second file -> newest used, flagged
        folder = Path(d) / "Deal A" / "Monthly Trustee Report" / "2026_08"
        (folder / "m (1).pdf").write_bytes((folder / "m.pdf").read_bytes())
        r = find_report(s, "Deal A", (2026, 8))
        assert r["file_status"] == "ok" and r["pdf"].endswith("m.pdf") and "identical" in r["file_note"]
        time.sleep(0.01)
        newer = make_pdf(folder / "z.pdf", "another version")
        os.utime(newer, None)
        r = find_report(s, "Deal A", (2026, 8))
        assert r["file_status"] == "check" and r["pdf"].endswith("z.pdf")

        # only a broken file -> broken; no month -> missing, with the latest month available
        (Path(d) / "Deal B" / "Monthly Trustee Report" / "2026_08").mkdir(parents=True)
        (Path(d) / "Deal B" / "Monthly Trustee Report" / "2026_08" / "r.pdf").write_bytes(b"junk")
        assert find_report(s, "Deal B", (2026, 8))["file_status"] == "broken"
        r = find_report(s, "Deal A", (2026, 9))
        assert r["file_status"] == "missing" and "latest is 2026-08" in r["file_note"]
