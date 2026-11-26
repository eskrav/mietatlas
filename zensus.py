"""The Zensus 2022 rent table (4000W-0004, Kreise): where it lives, how to parse and check it.

Needs only the standard library, so fetching and loading work without the geo packages.
"""
import csv
from pathlib import Path

from checks import DataCheckError, check

RAW = Path("data/raw")
RENT_CSV = RAW / "zensus2022_4000W-0004_nettokaltmiete_kreise.csv"

EXPECTED_KREISE = 400          # Gebietsstand 2022: 294 Landkreise + 106 kreisfreie Staedte
STICHTAG = "15.05.2022"        # census reference date in the Zensus table
YEAR = int(STICHTAG[-4:])      # year under which the values are stored in the database
INDICATOR_ID = "nettokaltmiete"
KNOWN_FLAGS = {"e"}            # quality flags we know how to handle ("e" = final value)
PLAUSIBLE_RANGE = (2.0, 20.0)  # EUR/m2; outside this, something likely went wrong in parsing
# Germany-wide value from the same table at "Deutschland" level. It is weighted by the
# number of rented flats, so it is NOT the mean of the 400 Kreis values. In the future,
# consider not hardcoding this, but rather reading it from the relevant Zensus table.
DEUTSCHLAND = 7.28


def load_rents(path: Path) -> dict:
    """Parse the table as returned by the Zensus API (see fetch_zensus.py).

    Layout: a few header lines, then the reference date on a line of its own,
    then one line per Kreis: AGS;name;value[;quality flag], then a footer that
    starts with underscores. AGS stays a string to keep leading zeros.
    """
    rents = {}
    in_data = False
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f, delimiter=";"):
            if not row:
                continue
            if row[0] == STICHTAG and not any(row[1:]):
                in_data = True  # data lines follow the reference date
                continue
            if row[0].startswith("___"):
                break  # footer
            if not in_data:
                continue
            check(len(row) in (3, 4), f"unexpected data line: {row}")
            ags, name, value = row[:3]
            flag = row[3] if len(row) == 4 else None  # flags only with quality=on
            check(ags not in rents, f"duplicate AGS in Zensus table: {ags}")
            try:
                miete = float(value.replace(",", "."))  # German decimal comma
            except ValueError:
                raise DataCheckError(f"non-numeric value for {ags} ({name}): {value!r}") from None
            rents[ags] = {"name": name, "miete": miete, "flag": flag}
    check(in_data, f"reference date {STICHTAG} not found in {path}")
    return rents


def validate_rents(rents: dict) -> None:
    """Checks on the raw file: quality flags, plus the value checks below."""
    flags = {r["flag"] for r in rents.values()}
    check(None not in flags, "quality flags missing (fetch with quality=on)")
    check(flags <= KNOWN_FLAGS, f"unknown quality flags: {flags - KNOWN_FLAGS}")
    validate_values(rents)


def validate_values(rents: dict) -> None:
    """Checks on the values, wherever they were read from (raw file or database)."""
    check(len(rents) == EXPECTED_KREISE, f"expected {EXPECTED_KREISE} Kreise, got {len(rents)}")
    bad_ags = [a for a in rents if not (len(a) == 5 and a.isdigit())]
    check(not bad_ags, f"malformed AGS codes: {bad_ags[:5]}")
    lo, hi = PLAUSIBLE_RANGE
    odd = {a: r["miete"] for a, r in rents.items() if not lo <= r["miete"] <= hi}
    check(not odd, f"implausible rent values: {odd}")
