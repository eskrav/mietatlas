"""Runs every query in db/queries.sql against the test database.

Keeps the example queries valid as the schema changes; queries named check_*
must return no rows.
"""
import re
from pathlib import Path

import psycopg
import pytest

import load_db

QUERIES = Path(__file__).parent.parent / "db" / "queries.sql"


def named_queries() -> dict:
    """Split queries.sql at its '-- name:' lines."""
    parts = re.split(r"^-- name: (\w+)\n", QUERIES.read_text(), flags=re.M)
    return {name: sql for name, sql in zip(parts[1::2], parts[2::2])}


QUERY_NAMES = list(named_queries())


@pytest.fixture(scope="module")
def loaded(db):
    load_db.main(db)
    return db


@pytest.mark.parametrize("name", QUERY_NAMES)
def test_query_runs(loaded, name):
    with psycopg.connect(loaded) as conn:
        conn.execute("SET search_path TO atlas")
        rows = conn.execute(named_queries()[name]).fetchall()
    if name.startswith("check_"):
        assert rows == [], f"{name} found problems: {rows[:5]}"
    else:
        assert rows, f"{name} returned no rows"


def test_kreise_below_national_value(loaded):
    with psycopg.connect(loaded) as conn:
        conn.execute("SET search_path TO atlas")
        rows = conn.execute(named_queries()["kreise_below_national_value"]).fetchall()
    land, kreise, below, _ = rows[0]
    assert (land, kreise, below) == ("Deutschland", 400, 297)
