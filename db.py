"""Database access: the connection setting and what the pipeline reads back from PostgreSQL."""
import os
import sys

import psycopg

from checks import check
from zensus import INDICATOR_ID, YEAR

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///mietatlas")


def load_rents_from_db(url: str = DATABASE_URL) -> tuple[dict, float]:
    """Read Kreis names and rents, and the national value, from the database
    that load_db.py fills from data/raw/."""
    try:
        conn = psycopg.connect(url)
    except psycopg.OperationalError as e:
        sys.exit(f"Cannot connect to the database ({e}).\n"
                 "Start PostgreSQL and run load_db.py before pipeline.py.")
    with conn, conn.cursor() as cur:
        try:
            cur.execute(
                """SELECT r.region_id, r.name, o.value
                   FROM atlas.observations o
                   JOIN atlas.regions r USING (region_id)
                   WHERE o.indicator_id = %s AND o.year = %s AND r.level = 'kreis'""",
                (INDICATOR_ID, YEAR),
            )
        except psycopg.errors.UndefinedTable:
            sys.exit("Database has no atlas tables yet; run load_db.py before pipeline.py.")
        rents = {ags: {"name": name, "miete": float(value)} for ags, name, value in cur}
        cur.execute(
            """SELECT value FROM atlas.observations
               WHERE region_id = 'DE' AND indicator_id = %s AND year = %s""",
            (INDICATOR_ID, YEAR),
        )
        row = cur.fetchone()
    check(row, "national value missing in the database")
    return rents, float(row[0])


# per Kreis and scenario: [highest rent EUR/m2, highest rent EUR/month, EUR/month at average growth]
SCENARIO_INDICATORS = ("nettokaltmiete_szenario", "monatsmiete_musterwohnung",
                       "monatsmiete_durchschnitt")


def load_scenarios_from_db(url: str = DATABASE_URL) -> dict:
    """Published scenarios of the example model, with what each run used, and the values
    per Kreis: {"szenarien": [...], "werte": {AGS: {scenario_id: [values in SCENARIO_INDICATORS order]}}}."""
    with psycopg.connect(url) as conn:
        try:
            runs = conn.execute(
                """SELECT s.scenario_id, s.name, s.description, s.is_baseline,
                          pr.run_id, pr.model_version, pr.data_release
                   FROM atlas.published_runs pr
                   JOIN atlas.scenarios s USING (scenario_id)
                   ORDER BY s.is_baseline DESC, s.scenario_id"""
            ).fetchall()
        except psycopg.errors.UndefinedTable:
            sys.exit("Database has no model tables yet; run run_model.py before pipeline.py.")
        params = {}
        for run_id, parameter_id, value in conn.execute(
            """SELECT run_id, parameter_id, value FROM atlas.run_parameters
               WHERE run_id = ANY(%s) ORDER BY run_id, parameter_id""",
            ([r[4] for r in runs],),
        ):
            params.setdefault(run_id, {})[parameter_id] = float(value)
        values = {}
        for scenario_id, ags, indicator_id, value in conn.execute(
            """SELECT p.scenario_id, p.region_id, p.indicator_id, p.value
               FROM atlas.published_results p
               JOIN atlas.regions r USING (region_id)
               WHERE r.level = 'kreis' AND p.indicator_id = ANY(%s)
               ORDER BY p.region_id, p.scenario_id, p.indicator_id""",
            (list(SCENARIO_INDICATORS),),
        ):
            row = values.setdefault(ags, {}).setdefault(scenario_id, [None] * len(SCENARIO_INDICATORS))
            row[SCENARIO_INDICATORS.index(indicator_id)] = float(value)
    scenarios = [
        {"id": sid, "name": name, "beschreibung": desc, "basis": base,
         "modellversion": version, "datenstand": release, "parameter": params.get(run_id, {})}
        for sid, name, desc, base, run_id, version, release in runs
    ]
    return {"szenarien": scenarios, "werte": values}
