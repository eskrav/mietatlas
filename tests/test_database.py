"""Loader and database read, against a real PostgreSQL.

Uses TEST_DATABASE_URL (default: postgresql:///mietatlas_test). Without a reachable
database these tests are skipped, unless REQUIRE_DB_TESTS=1 (as in GitHub Actions),
in which case they fail instead.
"""
import os

import psycopg
import pytest

import load_db
from pipeline import DEUTSCHLAND, RENT_CSV, load_rents, load_rents_from_db

URL = os.environ.get("TEST_DATABASE_URL", "postgresql:///mietatlas_test")


@pytest.fixture(scope="module")
def db():
    try:
        psycopg.connect(URL).close()
    except psycopg.OperationalError as e:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail(f"test database not reachable: {e}")
        pytest.skip(f"no test database at {URL} (createdb mietatlas_test to run these)")
    return URL


def counts(url):
    with psycopg.connect(url) as conn:
        regions = conn.execute("SELECT count(*) FROM atlas.regions").fetchone()[0]
        observations = conn.execute("SELECT count(*) FROM atlas.observations").fetchone()[0]
    return regions, observations


def test_load_is_repeatable(db):
    load_db.main(db)
    first = counts(db)
    load_db.main(db)
    assert counts(db) == first == (1 + 16 + 400, 400 + 1)


def test_failed_load_changes_nothing(db, monkeypatch):
    load_db.main(db)
    before = counts(db)
    monkeypatch.setitem(load_db.FLAG_STATUS, "e", "not-a-status")  # violates the CHECK
    with pytest.raises(psycopg.errors.CheckViolation):
        load_db.main(db)
    assert counts(db) == before


def test_database_returns_what_the_raw_file_says(db):
    load_db.main(db)
    from_db, deutschland = load_rents_from_db(db)
    raw = load_rents(RENT_CSV)
    assert {a: r["miete"] for a, r in from_db.items()} == {a: r["miete"] for a, r in raw.items()}
    assert {a: r["name"] for a, r in from_db.items()} == {a: r["name"] for a, r in raw.items()}
    assert deutschland == DEUTSCHLAND


def test_regions_hierarchy(db):
    load_db.main(db)
    with psycopg.connect(db) as conn:
        wrong = conn.execute(
            """SELECT k.region_id FROM atlas.regions k
               JOIN atlas.regions p ON p.region_id = k.parent_id
               WHERE k.level = 'kreis' AND (p.level <> 'land' OR left(k.region_id, 2) <> p.region_id)"""
        ).fetchall()
    assert wrong == []
