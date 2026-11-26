"""Loader and database read, against a real PostgreSQL (fixture db in conftest.py)."""
import psycopg
import pytest

import load_db
from db import load_rents_from_db
from zensus import DEUTSCHLAND, RENT_CSV, load_rents


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


def test_each_load_is_logged_with_the_checksum_of_the_raw_file(db):
    import hashlib

    load_db.main(db)
    with psycopg.connect(db) as conn:
        n_before = conn.execute("SELECT count(*) FROM atlas.data_loads").fetchone()[0]
    load_db.main(db)
    with psycopg.connect(db) as conn:
        n, sha, n_obs = conn.execute(
            """SELECT (SELECT count(*) FROM atlas.data_loads), file_sha256, n_observations
               FROM atlas.data_loads ORDER BY load_id DESC LIMIT 1"""
        ).fetchone()
    assert n == n_before + 1
    assert sha == hashlib.sha256(RENT_CSV.read_bytes()).hexdigest()
    assert n_obs == 401
