"""table.build_table: one test per rule (synthetic words, no PDFs)."""
from helpers import line, lines, table_words

from wit.table import build_table


def test_simple_table():
    df = build_table(table_words(["Issuer", "ID", "Balance"],
                                 [["Alpha Ltd", "LX100001", "1,000.00"],
                                  ["Beta SA", "LX100002", "2,000.00"]]))
    assert list(df.columns) == ["Issuer", "ID", "Balance"]
    assert df.values.tolist() == [["Alpha Ltd", "LX100001", "1,000.00"], ["Beta SA", "LX100002", "2,000.00"]]


def test_columns_come_from_data_not_header():
    # two header names printed touching each other ("Loan ID" "Rating"), values clearly apart
    words = lines(line(10, (10, "Issuer"), (100, "Loan ID Rating")),
                  line(24, (10, "Alpha"), (100, "LX100001"), (160, "B2")),
                  line(38, (10, "Beta"), (100, "LX100002"), (160, "B3")))
    df = build_table(words, vocab=["loan id", "rating"])
    assert list(df.columns) == ["Issuer", "Loan ID", "Rating"]
    assert df["Rating"].tolist() == ["B2", "B3"]


def test_empty_column_keeps_its_header():
    # 'Watch' has no values this month: still its own column, not glued to a neighbour
    df = build_table(table_words(["Issuer", "Watch", "Balance"],
                                 [["Alpha", "", "1,000.00"], ["Beta", "", "2,000.00"]]))
    assert list(df.columns) == ["Issuer", "Watch", "Balance"]
    assert df["Watch"].tolist() == ["", ""]


def test_date_in_header_stays_header():
    words = lines(line(10, (10, "Test"), (120, "Current"), (230, "Prior")),
                  line(24, (120, "5/2/2024"), (230, "4/3/2024")),
                  line(38, (10, "Par Value"), (120, "140.40%"), (230, "140.42%")))
    df = build_table(words)
    assert len(df) == 1
    assert list(df.columns) == ["Test", "Current 5/2/2024", "Prior 4/3/2024"]


def test_key_value_lines_are_data():
    words = lines(line(10, (10, "Calculation Date:"), (150, "05/02/2024")),
                  line(24, (10, "Principal Amount:"), (150, "1,000.00")),
                  line(38, (10, "Proceeds:"), (150, "-50.00")))
    df = build_table(words)
    assert df.iloc[:, 0].tolist() == ["Calculation Date:", "Principal Amount:", "Proceeds:"]


def test_wrapped_cell_below_is_glued():
    # top-aligned cell: the issuer's second line sits under its row
    words = lines(line(10, (10, "Issuer"), (150, "ID"), (260, "Balance")),
                  line(24, (10, "Alpha Holdings"), (150, "LX100001"), (260, "1,000.00")),
                  line(38, (10, "Limited")),
                  line(52, (10, "Beta SA"), (150, "LX100002"), (260, "2,000.00")))
    df = build_table(words)
    assert df["Issuer"].tolist() == ["Alpha Holdings Limited", "Beta SA"]


def test_centred_cell_lines_above_and_below_are_glued():
    # centred 2-line cells: one text line just ABOVE the row, one just BELOW (half a line away)
    words = lines(line(10, (10, "Issuer"), (150, "ID"), (260, "Balance"), (370, "Country")),
                  line(24, (10, "Alpha"), (150, "LX100001"), (260, "1,000.00"), (370, "France")),
                  line(42, (370, "United Kingdom")),
                  line(47, (10, "Beta Ltd"), (150, "LX100002"), (260, "2,000.00")),
                  line(52, (370, "(Great Britain)")),
                  line(66, (10, "Gamma"), (150, "LX100003"), (260, "3,000.00"), (370, "Spain")))
    df = build_table(words)
    assert df["Country"].tolist() == ["France", "United Kingdom (Great Britain)", "Spain"]


def test_total_line_is_never_glued_to_the_last_row():
    words = lines(line(10, (10, "Issuer"), (150, "ID"), (260, "Balance")),
                  line(24, (10, "Alpha"), (150, "LX100001"), (260, "1,000.00")),
                  line(38, (10, "Beta"), (150, "LX100002"), (260, "2,000.00")),
                  line(52, (150, "Total Balance:"), (260, "3,000.00")))
    df = build_table(words)
    assert len(df) == 3
    assert df["Balance"].tolist()[-1] == "3,000.00"


def test_section_labels_become_a_column():
    # sections as printed: label, rows, '<label> Subtotal:' line, next label ...
    words = lines(line(10, (10, "Description"), (150, "ID"), (260, "Balance")),
                  line(24, (10, "Loan")),
                  line(38, (10, "Alpha"), (150, "LX100001"), (260, "1,000.00")),
                  line(52, (150, "Loan Subtotal:"), (260, "1,000.00")),
                  line(66, (10, "Bond")),
                  line(80, (10, "Beta"), (150, "XS0000000001"), (260, "2,000.00")))
    df = build_table(words)
    assert df["Description"].tolist() == ["Alpha", "", "Beta"]
    assert df["_section"].tolist() == ["Loan", "Loan", "Bond"]


def test_lone_word_right_after_a_row_is_a_wrapped_cell():
    # known limit: a one-word line directly under a row (no subtotal before it) is read as the
    # wrapped end of that row's first cell, not as a new section label
    words = lines(line(10, (10, "Description"), (150, "ID"), (260, "Balance")),
                  line(24, (10, "Alpha"), (150, "LX100001"), (260, "1,000.00")),
                  line(38, (10, "Holdings")),
                  line(52, (10, "Beta"), (150, "LX100002"), (260, "2,000.00")))
    df = build_table(words)
    assert df["Description"].tolist() == ["Alpha Holdings", "Beta"]


def test_no_data_message_is_ignored():
    words = lines(line(10, (10, "Issuer"), (150, "Balance")),
                  line(24, (10, "There are no defaulted obligations to report.")))
    df = build_table(words)
    assert len(df) <= 1 and "There" not in " ".join(df.columns)
