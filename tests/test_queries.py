"""Runs every query in db/queries.sql and db/model_queries.sql against the test database.

Keeps the example queries valid as the schema changes; queries named check_*
must return no rows, all others must return at least one.
"""
import re
from pathlib import Path

import psycopg
import pytest

import load_db

DB_DIR = Path(__file__).parent.parent / "db"
QUERY_FILES = ["queries.sql", "model_queries.sql"]


def named_queries(filename: str) -> dict:
    """Split a query file at its '-- name:' lines."""
    parts = re.split(r"^-- name: (\w+)\n", (DB_DIR / filename).read_text(), flags=re.M)
    return {name: sql for name, sql in zip(parts[1::2], parts[2::2])}


ALL_QUERIES = [(f, name) for f in QUERY_FILES for name in named_queries(f)]


@pytest.fixture(scope="module")
def loaded(db):
    """Real data via load_db.py, plus the Kappungsgrenze model computed on it."""
    load_db.main(db)
    with psycopg.connect(db) as conn:
        conn.execute((DB_DIR / "model_schema.sql").read_text())
        conn.execute((DB_DIR / "model_kappung.sql").read_text())
    return db


def run(url: str, filename: str, name: str) -> list:
    with psycopg.connect(url) as conn:
        conn.execute("SET search_path TO atlas")
        return conn.execute(named_queries(filename)[name]).fetchall()


@pytest.mark.parametrize("filename, name", ALL_QUERIES, ids=[n for _, n in ALL_QUERIES])
def test_query_runs(loaded, filename, name):
    rows = run(loaded, filename, name)
    if name.startswith("check_"):
        assert rows == [], f"{name} found problems: {rows[:5]}"
    else:
        assert rows, f"{name} returned no rows"


def test_kreise_below_national_value(loaded):
    land, kreise, below, _ = run(loaded, "queries.sql", "kreise_below_national_value")[0]
    assert (land, kreise, below) == ("Deutschland", 400, 297)


def scalar(url: str, sql: str):
    with psycopg.connect(url) as conn:
        return conn.execute(sql).fetchone()[0]


def test_reforms_affect_only_tight_kreise(loaded):
    rows = run(loaded, "model_queries.sql", "scenario_overview")
    affected = {name: n for name, n, *_ in rows}
    assert affected["Geltendes Recht"] == 0
    # tight = rent at or above the national value: the 103 Kreise not below it
    assert affected["Kappungsgrenze 10 % in angespannten Märkten"] == 103
    # 15 % everywhere changes only the other 297; tight Kreise already have 15 %
    assert affected["Kappungsgrenze 15 % überall"] == 297


def test_berlin_lookup(loaded):
    rows = {name: (float(m2), int(month), int(diff))
            for name, m2, month, diff in run(loaded, "model_queries.sql", "kreis_lookup")}
    assert rows["Geltendes Recht"] == (8.82, 617, 0)    # 7.67 × 1.15, × 70 m²
    assert rows["Kappungsgrenze 10 % in angespannten Märkten"] == (8.44, 591, -26)
    assert rows["Kappungsgrenze 15 % überall"] == (8.82, 617, 0)  # Berlin is already tight


def test_published_baseline_uses_latest_run(loaded):
    # A Kreis below the national value: the cap does not bind, so the market growth
    # assumption shows. Run 1 used 5 % (410 EUR), the published run 2 uses 6 % (421 EUR).
    value = scalar(loaded, """SELECT value FROM atlas.published_results
                              WHERE scenario_id = 'geltendes_recht' AND region_id = '14522'
                                AND indicator_id = 'monatsmiete_musterwohnung'""")
    assert int(value) == 421


def test_unpublished_scenario_is_hidden(loaded):
    n = scalar(loaded, "SELECT count(*) FROM atlas.published_results "
                       "WHERE scenario_id = 'schwelle_120'")
    assert n == 0


def test_trace_shows_the_changed_parameter(loaded):
    rows = run(loaded, "model_queries.sql", "trace_published_number")
    changed = [(r[4], float(r[5])) for r in rows if r[8]]
    assert changed == [("kappung_angespannt", 0.10)]


def test_model_run_is_repeatable(loaded):
    with psycopg.connect(loaded) as conn:
        conn.execute((DB_DIR / "model_kappung.sql").read_text())
    n = scalar(loaded, "SELECT count(*) FROM atlas.results")
    assert n == 5 * 400 * 2  # runs × Kreise × indicators
