import pytest

from trustee_extract.cli import main, parse_pages


def test_parse_pages():
    assert parse_pages("1") == [1]
    assert parse_pages("1,4,7-9") == [1, 4, 7, 8, 9]
    assert parse_pages("3-4,4") == [3, 4]


def test_stub_commands_exit_2(capsys):
    assert main(["eval", "data/golden"]) == 2
    assert "not implemented" in capsys.readouterr().err


def test_unknown_command_fails():
    with pytest.raises(SystemExit):
        main(["nope"])
