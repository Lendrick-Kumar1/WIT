"""totals.mark_totals / stitch_pages: one test per rule."""
import pandas as pd

from wit.totals import mark_totals, stitch_pages


def df(cols, rows):
    return pd.DataFrame(rows, columns=cols)


GROUPED = ["Industry", "Score", "Issuer", "Balance"]


def test_grouped_table_copies_group_down_and_checks_subtotal():
    t = df(GROUPED, [["Automotive", "2.23", "Alpha", "1,000.00"],
                     ["", "", "Beta", "2,000.00"],
                     ["Automotive", "", "", ""],          # label line of the subtotal
                     ["", "", "", "3,000.00"]])           # the subtotal amount
    m = mark_totals(t)
    assert m["Industry"].tolist() == ["Automotive", "Automotive", "Automotive"]
    assert m["Score"].tolist()[:2] == ["2.23", "2.23"]
    assert m["_row"].tolist() == ["detail", "detail", "subtotal"]
    assert m["_check"].tolist()[-1] == "ok"


def test_subtotal_that_does_not_add_up_is_flagged():
    t = df(GROUPED, [["Automotive", "2.23", "Alpha", "1,000.00"],
                     ["", "", "Beta", "2,000.00"],
                     ["Automotive", "", "", ""],
                     ["", "", "", "3,500.00"],             # 500 more than its rows
                     ["Banking", "1.10", "Gamma", "500.00"],
                     ["", "", "Delta", "400.00"],
                     ["Banking", "", "", ""],
                     ["", "", "", "950.00"]])              # 50 more than its rows
    m = mark_totals(t)
    checks = m.loc[m["_row"] == "subtotal", "_check"].tolist()
    assert checks[0].startswith("check:") and "earlier page" in checks[0]   # first group: may continue
    assert checks[1].startswith("check:") and "earlier page" not in checks[1]


def test_single_row_groups_still_check_out():
    # when most groups have ONE row the group column looks dense, so the table is not seen as
    # grouped; each sum then closes the rows since the previous sum - still the right rows
    t = df(GROUPED, [["Automotive", "2.23", "Alpha", "1,000.00"],
                     ["Automotive", "", "", ""], ["", "", "", "1,000.00"],
                     ["Banking", "1.10", "Gamma", "500.00"],
                     ["Banking", "", "", ""], ["", "", "", "500.00"]])
    m = mark_totals(t)
    assert m.loc[m["_row"] != "detail", "_check"].tolist() == ["ok", "ok"]


def test_section_subtotals_and_grand_total():
    t = df(["Description", "ID", "Balance", "_section"],
           [["Alpha", "LX100001", "1,000.00", "Loan"],
            ["Beta", "LX100002", "2,000.00", "Loan"],
            ["", "Loan Subtotal:", "3,000.00", "Loan"],
            ["Gamma", "XS0000000001", "500.00", "Bond"],
            ["", "Bond Subtotal:", "500.00", "Bond"],
            ["", "Total:", "3,500.00", "Bond"]])
    m = mark_totals(t)
    assert m["_row"].tolist() == ["detail", "detail", "subtotal", "detail", "subtotal", "total"]
    assert m.loc[m["_row"] != "detail", "_check"].tolist() == ["ok", "ok", "ok"]


def test_total_whose_rows_are_on_an_earlier_page():
    t = df(GROUPED, [["", "", "", "1,214.00"],               # subtotal of a group from the page before
                     ["Energy", "1.00", "Alpha", "3,930.00"],
                     ["Energy", "", "", ""],
                     ["", "", "", "3,930.00"]])
    m = mark_totals(t)
    assert m["_check"].tolist()[0] == "check: its rows are on an earlier page"
    assert m["_check"].tolist()[-1] == "ok"


def test_labelled_figure_in_a_key_value_box_is_not_a_total():
    t = df(["Item", "Value"], [["Average Balance", "3,079,536.31"],
                               ["Number of Issuers", "145"],
                               ["Total Principal Balance", "446,532,764.57"]])
    m = mark_totals(t)
    assert m["_row"].tolist() == ["detail", "detail", "detail"]


def test_stitch_joins_last_table_with_first_table_of_next_page():
    a = df(GROUPED, [["Automotive", "2.23", "Alpha", "1,000.00"]]).assign(_page=1)
    b = df(GROUPED, [["", "", "Beta", "2,000.00"], ["Automotive", "", "", ""], ["", "", "", "3,000.00"]]).assign(_page=2)
    other = df(["Item", "Value"], [["x", "1"]]).assign(_page=2)
    joined = stitch_pages([(0, a), (1, b), (1, other)])
    assert [p for p, _ in joined] == [[0, 1], [1]]
    m = mark_totals(joined[0][1])
    assert m["_check"].tolist()[-1] == "ok"                 # subtotal checked across the page break


def test_stitch_carries_section_over_page_break():
    a = df(["Description", "ID", "Balance", "_section"], [["Alpha", "LX100001", "1,000.00", "Loan"]])
    b = df(["Description", "ID", "Balance"], [["Beta", "LX100002", "2,000.00"], ["", "Loan Subtotal:", "3,000.00"]])
    (pages, t), = stitch_pages([(0, a), (1, b)])
    assert t["_section"].tolist() == ["Loan", "Loan", "Loan"]
    assert mark_totals(t)["_check"].tolist()[-1] == "ok"


def test_separate_tables_on_consecutive_pages_are_not_joined():
    a = df(["Class", "Balance"], [["A", "100.00"]])
    b = df(["Class", "Balance"], [["B", "50.00"]])
    first_on_2 = df(["Item", "Value"], [["x", "1"]])
    joined = stitch_pages([(0, a), (1, first_on_2), (1, b)])
    assert len(joined) == 3


def test_group_total_printed_on_the_groups_first_line():
    t = df(["Issuer", "Facility", "ID", "Balance"],
           [["Alpha Corp", "", "", "3,000.00"],                   # the group's total, on its first line
            ["", "Term Loan B", "LX100001", "1,000.00"],
            ["", "Term Loan C", "LX100002", "2,000.00"],
            ["Beta Inc", "", "", "500.00"],
            ["", "Term Loan", "LX100003", "500.00"],
            ["Gamma SA", "", "", "700.00"],
            ["", "Term Loan", "LX100004", "300.00"],
            ["", "Revolver", "LX100005", "400.00"],
            ["Total", "", "", "4,200.00"]])
    m = mark_totals(t)
    assert m["_row"].tolist() == ["subtotal", "detail", "detail", "subtotal", "detail", "subtotal", "detail", "detail",
                                  "total"]
    assert m.loc[m["_row"] == "detail", "Issuer"].tolist() == ["Alpha Corp"] * 2 + ["Beta Inc"] + ["Gamma SA"] * 2
    assert all(c.startswith("ok") for c in m.loc[m["_row"] != "detail", "_check"])


def test_total_printed_above_the_header_is_checked_after_the_last_row():
    a = df(["Issuer", "Balance"], [["Alpha", "1,000.00"]])
    a.attrs["totals_above"] = [{"Issuer": "Grand Totals:", "Balance": "3,000.00"}]
    b = df(["Issuer", "Balance"], [["Beta", "2,000.00"]])
    (pages, t), = stitch_pages([(0, a), (1, b)])
    m = mark_totals(t)
    assert m["_row"].tolist()[-1] == "total" and m["_check"].tolist()[-1] == "ok"
