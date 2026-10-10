"""collateral: header mapping, IDs, joining tables on the security ID."""
import pandas as pd

from wit.collateral import header_rank, join_on_id, map_headers, norm_id
from wit.config import load_trustees

DEFAULTS, _ = load_trustees()
CFG = DEFAULTS
COLS = CFG["collateral"]["columns"]
IDS = CFG["collateral"]["id_patterns"]


def test_header_that_is_the_field_name_wins():
    m = map_headers(["Description", "Security ID", "Par/Quantity", "Principal Balance"], COLS)
    assert m["Principal Balance"] == "principal balance" and "Par/Quantity" not in m


def test_first_header_wins_otherwise():
    m = map_headers(["Identifier", "Bloomberg FIGI"], COLS)
    assert m == {"Identifier": "loan id"}


def test_header_rank():
    assert header_rank("Issuer", "issuer", COLS) == 0
    assert header_rank("Issuer Name", "issuer", COLS) < header_rank("Description", "issuer", COLS)


def test_norm_id_picks_the_id_token():
    assert norm_id("NEW B2D LX218697", IDS) == "LX218697"
    assert norm_id("XS2231188876", IDS) == "XS2231188876"
    assert norm_id("Term Loan", IDS) == ""


def tables(*dfs):
    return [(k + 1, d) for k, d in enumerate(dfs)]


def test_rows_from_table_with_most_distinct_securities():
    assets = pd.DataFrame([["Alpha", "LX100001", "1,309,159.90"], ["Beta", "LX100002", "500.00"]],
                          columns=["Issuer", "Security ID", "Principal Balance"])
    lots = pd.DataFrame([["Alpha", "LX100001", "445,979.01", "Quarterly"],     # one security in 2 lots
                         ["Alpha", "LX100001", "863,180.89", "Quarterly"],
                         ["Beta", "LX100002", "500.00", "Monthly"]],
                        columns=["Issuer", "Security ID", "Principal Balance", "Payment Period"])
    rows = join_on_id(tables(lots, assets), CFG).set_index("loan id")
    assert rows.loc["LX100001", "principal balance"] == 1309159.90
    assert rows.loc["LX100001", "payment period"] == "Quarterly"


def test_each_column_from_the_most_specific_header():
    a = pd.DataFrame([["Alpha Ltd - Term Loan B", "LX100001", "1,000.00"]],
                     columns=["Description", "Security ID", "Principal Balance"])
    b = pd.DataFrame([["Alpha Ltd", "LX100001", "B2"]], columns=["Issuer Name", "Security ID", "Moody's Rating"])
    rows = join_on_id(tables(a, b), CFG).set_index("loan id")
    assert rows.loc["LX100001", "issuer"] == "Alpha Ltd"
    assert rows.loc["LX100001", "moody's rating"] == "B2"


def test_no_id_column_gives_nothing():
    a = pd.DataFrame([["Alpha", "1,000.00", "x"]], columns=["Issuer", "Principal Balance", "Other"])
    assert join_on_id(tables(a), CFG) is None
