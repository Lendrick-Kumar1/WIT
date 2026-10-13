"""pdfpage.to_num, and the measured title block / footer of crops."""
from helpers import line, lines

from wit.crops import footer_top, title_bottom
from wit.pdfpage import to_num


def test_to_num():
    assert to_num("1,234.50") == 1234.5
    assert to_num("(1,234.50)") == -1234.5
    assert to_num(">= 120.00%") == 120.0
    assert to_num("€2,000,000.00") == 2000000.0
    assert to_num("1,000.00 EUR") == 1000.0
    assert to_num("4.19%", percent=False) is None
    assert to_num("Term Loan") is None and to_num("5/2/2024") is None


def big(y, x, text):
    """A title line: 15 pt high instead of 10."""
    return [dict(w, y1=w["y0"] + 15) for w in line(y, (x, text))]


def test_title_block_is_measured():
    body = [line(94 + 14 * i, (10, f"Issuer{i} Holdings"), (200, f"{i},000.00")) for i in range(20)]
    words = lines(big(10, 200, "Deal Name CLO"), big(28, 220, "Detail of Assets"),
                  big(46, 220, "As of: 5/2/2024"),
                  line(80, (10, "Issuer"), (200, "Balance")),            # table header: not title
                  *body)
    assert 60 < title_bottom(words, 612) < 80


def test_footer_is_measured_and_last_row_is_kept():
    body = [line(100 + 14 * i, (10, f"Row{i}"), (200, f"{i},000.00")) for i in range(30)]
    last_row_y = 100 + 14 * 29                                           # 506: kept
    words = lines(*body, line(575, (10, "Report name as of 01-Jan-2025"), (500, "Page 9 of 48")))
    top = footer_top(words, 612)
    assert last_row_y + 10 < top < 575


def test_footer_found_by_its_page_number_without_a_gap():
    # the footer sits at the normal line step under the last row; 'Page 9 of 48' gives it away
    body = [line(100 + 14 * i, (10, f"Row{i}"), (200, f"{i},000.00")) for i in range(30)]
    words = lines(*body, line(100 + 14 * 30, (10, "Trustee report"), (500, "Page 9 of 48")))
    assert 100 + 14 * 29 + 10 < footer_top(words, 612) <= 100 + 14 * 30
