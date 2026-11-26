"""The model tables (db/model_schema.sql): created repeatably, constraints enforced."""
from pathlib import Path

import psycopg
import pytest

import load_db

MODEL_SCHEMA = Path(__file__).parent.parent / "db" / "model_schema.sql"
MODEL_TABLES = ("results", "run_parameters", "model_runs", "scenario_overrides",
                "scenarios", "parameters", "household_types")


@pytest.fixture
def conn(db):
    """Connection with an empty model schema; everything is rolled back afterwards."""
    load_db.main(db)
    with psycopg.connect(db) as c:
        c.execute(MODEL_SCHEMA.read_text())
        c.execute(MODEL_SCHEMA.read_text())  # creating it twice must work
        c.commit()
    c = psycopg.connect(db)
    c.execute(f"TRUNCATE {', '.join('atlas.' + t for t in MODEL_TABLES)} RESTART IDENTITY CASCADE")
    yield c
    c.rollback()
    c.close()


def add_parameter(conn, pid="kappungsgrenze", baseline=0.20, lo=0.0, hi=0.5):
    conn.execute(
        """INSERT INTO atlas.parameters
               (parameter_id, name, unit, baseline_value, kind, valid_min, valid_max)
           VALUES (%s, %s, 'Anteil', %s, 'lever', %s, %s)""",
        (pid, pid, baseline, lo, hi),
    )


def test_tables_and_views_exist(conn):
    names = {r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'atlas'")}
    assert set(MODEL_TABLES) | {"effective_parameters", "published_results"} <= names


def test_only_one_baseline(conn):
    conn.execute("INSERT INTO atlas.scenarios (scenario_id, name, is_baseline) VALUES ('a', 'A', true)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO atlas.scenarios (scenario_id, name, is_baseline) VALUES ('b', 'B', true)")


def test_baseline_value_must_lie_in_valid_range(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        add_parameter(conn, baseline=0.8, hi=0.5)


def test_effective_parameters_fall_back_to_baseline(conn):
    add_parameter(conn, "kappungsgrenze", 0.20)
    add_parameter(conn, "horizont", 3, lo=1, hi=10)
    conn.execute("INSERT INTO atlas.scenarios (scenario_id, name) VALUES ('k15', 'Kappung 15 %')")
    conn.execute("""INSERT INTO atlas.scenario_overrides (scenario_id, parameter_id, value)
                    VALUES ('k15', 'kappungsgrenze', 0.15)""")
    rows = dict(conn.execute("""SELECT parameter_id, value FROM atlas.effective_parameters
                                WHERE scenario_id = 'k15'""").fetchall())
    assert {k: float(v) for k, v in rows.items()} == {"kappungsgrenze": 0.15, "horizont": 3.0}


def test_published_results_only_latest_run_of_published_scenarios(conn):
    conn.execute("INSERT INTO atlas.household_types VALUES ('single', 'Single')")
    conn.execute("""INSERT INTO atlas.scenarios (scenario_id, name, is_published)
                    VALUES ('pub', 'Published', true), ('draft', 'Draft', false)""")
    conn.execute("""INSERT INTO atlas.model_runs (run_id, scenario_id, model_version, data_release, run_at)
                    VALUES (1, 'pub', 'v1', 'r1', '2026-01-01'), (2, 'pub', 'v2', 'r1', '2026-02-01'),
                           (3, 'draft', 'v2', 'r1', '2026-02-01')""")
    conn.execute("""INSERT INTO atlas.results VALUES
                    (1, '11000', 'single', 'nettokaltmiete', 2025, 1.0),
                    (2, '11000', 'single', 'nettokaltmiete', 2025, 2.0),
                    (3, '11000', 'single', 'nettokaltmiete', 2025, 3.0)""")
    rows = conn.execute("SELECT scenario_id, value FROM atlas.published_results").fetchall()
    assert [(s, float(v)) for s, v in rows] == [("pub", 2.0)]
