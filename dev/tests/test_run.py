"""run: where output files go."""
import helpers  # noqa: F401  (puts src/ on the path)

from wit.run import output_path


def test_output_path_fills_deal_and_month_and_cleans_the_name():
    settings = {"output": {"balance": {"dir": "/out/Balance/{yyyy}", "file": "{deal}_{yyyy}_{mm}.xlsx"}}}
    job = {"deal": "Deal A/B: 2021-1", "year": 2026, "month": 8}
    p = output_path(job, "balance", settings)
    assert p.as_posix() == "/out/Balance/2026/Deal A_B_ 2021-1_2026_08.xlsx"
