"""performance: header found by its words, rows read below it (in-memory PDF pages, no files)."""
import helpers  # noqa: F401  (puts src/ on the path)
import pymupdf

from wit.config import load_trustees
from wit.performance import performance, role_of

CFG, _ = load_trustees()
COLS = {"test": 40, "trigger": 300, "current": 380, "result": 460}


def page(*lines):
    """lines = (y, {column: text}, fontsize) -> a one-page PDF page."""
    doc = pymupdf.open()
    p = doc.new_page(width=600, height=800)
    for y, cells, size in lines:
        for col, text in cells.items():
            p.insert_text((COLS.get(col, col), y), text, fontsize=size)
    return p


def row(y, test, trigger="", current="", result="", size=8):
    return (y, {k: v for k, v in dict(test=test, trigger=trigger, current=current, result=result).items() if v}, size)


def test_current_result_header_is_current_not_result():
    # 'Current Result' holds the value, 'Result' the pass/fail: current is checked before result
    roles = CFG["performance"]["header_roles"]
    assert role_of("Current Result", roles) == "current" and role_of("Result", roles) == "result"


def test_header_line_below_the_result_line():
    # the dates of the header are printed on a line UNDER the result line
    p = page((100, {"test": "Test", "trigger": "Trigger", "current": "Current Result", "result": "Result"}, 8),
             (111, {"current": "15-Jul-2025"}, 8),
             row(130, "Class A Par Value Test", "120.00%", "135.00%", "Passed"),
             row(144, "Class B Par Value Test", "110.00%", "125.00%", "Passed"))
    recs = performance(p, CFG)
    assert [r["test"] for r in recs] == ["Class A Par Value Test", "Class B Par Value Test"]
    assert recs[0]["current"] == 135.0 and recs[0]["trigger"] == 120.0


def test_wrapped_test_name_is_glued_and_section_label_is_not():
    # a test name wraps onto a second line (no digits); the next section's label is printed larger
    p = page((100, {"test": "Test", "trigger": "Trigger", "current": "Current", "result": "Result"}, 8),
             row(130, "(a) Exposure to a Selling Institution", "5.0%", "0.0%", "Passed"),
             row(140, "rated Aaa or below"),
             row(154, "(b) Exposure to a Selling Institution", "5.0%", "0.0%", "Passed"),
             row(164, "rated AA or below"),
             (180, {30: "Other Tests"}, 11),
             row(196, "(c) Weighted Average Life", "5.0", "4.1", "Passed"))
    recs = performance(p, CFG)
    assert [r["test"] for r in recs] == ["(a) Exposure to a Selling Institution rated Aaa or below",
                                         "(b) Exposure to a Selling Institution rated AA or below",
                                         "(c) Weighted Average Life"]
