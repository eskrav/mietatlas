"""Parser and value checks, on small made-up tables in the layout of the Zensus API."""
import pytest

from checks import DataCheckError
from zensus import EXPECTED_KREISE, RENT_CSV, load_rents, validate_rents, validate_values

HEADER = """﻿Tabelle: 4000W-0004
Wohnungskennzahlen: Durchschnittliche Nettokaltmiete;;
Wohnungen (Gebietsstand 15.05.2022);;;
;;Durchschnittliche Nettokaltmiete;
;;?/m²;?/m²
15.05.2022;;;
"""
FOOTER = """__________
© Statistische Ämter des Bundes und der Länder, Deutschland, 2026.
Stand: 26.11.2026 / 12:00:04
"""


def table(tmp_path, *lines, header=HEADER, footer=FOOTER):
    path = tmp_path / "table.csv"
    path.write_text(header + "\n".join(lines) + "\n" + footer, encoding="utf-8")
    return path


def test_parses_api_layout(tmp_path):
    rents = load_rents(table(tmp_path, "01001;Flensburg, Stadt;6,96;e", "09162;München;12,89;e"))
    assert rents == {
        "01001": {"name": "Flensburg, Stadt", "miete": 6.96, "flag": "e"},
        "09162": {"name": "München", "miete": 12.89, "flag": "e"},
    }


def test_keeps_leading_zeros(tmp_path):
    rents = load_rents(table(tmp_path, "01001;Flensburg, Stadt;6,96;e"))
    assert list(rents) == ["01001"]


def test_ignores_lines_after_footer(tmp_path):
    path = table(tmp_path, "01001;Flensburg, Stadt;6,96;e", footer=FOOTER + "99999;Nirgendwo;1,00;e\n")
    assert list(load_rents(path)) == ["01001"]


def test_missing_flags_are_parsed_but_rejected(tmp_path):
    rents = load_rents(table(tmp_path, "01001;Flensburg, Stadt;6,96"))
    assert rents["01001"]["flag"] is None
    with pytest.raises(DataCheckError, match="quality flags missing"):
        validate_rents(rents)


def test_unknown_flag_is_rejected(tmp_path):
    rents = load_rents(table(tmp_path, "01001;Flensburg, Stadt;6,96;x"))
    with pytest.raises(DataCheckError, match="unknown quality flags"):
        validate_rents(rents)


@pytest.mark.parametrize(
    "line, message",
    [
        ("15.05.2022;01001;Flensburg, Stadt;6,96;e", "unexpected data line"),  # website layout
        ("01001;Flensburg, Stadt;-;e", "non-numeric value"),
    ],
)
def test_bad_data_lines(tmp_path, line, message):
    with pytest.raises(DataCheckError, match=message):
        load_rents(table(tmp_path, line))


def test_duplicate_ags(tmp_path):
    path = table(tmp_path, "01001;Flensburg, Stadt;6,96;e", "01001;Flensburg, Stadt;7,00;e")
    with pytest.raises(DataCheckError, match="duplicate AGS"):
        load_rents(path)


def test_missing_reference_date(tmp_path):
    header = HEADER.replace("15.05.2022;;;\n", "")
    with pytest.raises(DataCheckError, match="reference date"):
        load_rents(table(tmp_path, "01001;Flensburg, Stadt;6,96;e", header=header))


def kreise(n=EXPECTED_KREISE, value=6.0):
    return {f"{i:05d}": {"name": f"Kreis {i}", "miete": value, "flag": "e"} for i in range(1, n + 1)}


def test_validate_values_accepts_plausible_data():
    validate_values(kreise())


@pytest.mark.parametrize(
    "rents, message",
    [
        (kreise(n=399), "expected 400 Kreise"),
        (kreise(value=45.0), "implausible rent values"),
        ({**kreise(n=399), "1234": {"name": "x", "miete": 6.0, "flag": "e"}}, "malformed AGS"),
    ],
)
def test_validate_values_rejects(rents, message):
    with pytest.raises(DataCheckError, match=message):
        validate_values(rents)


def test_committed_raw_file_passes_all_checks():
    rents = load_rents(RENT_CSV)
    validate_rents(rents)
    assert rents["09162"]["miete"] == 12.89  # München, the maximum
