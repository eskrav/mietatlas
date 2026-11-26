"""Load the checked Zensus rents into PostgreSQL (schema in db/schema.sql).

    export DATABASE_URL=postgresql:///mietatlas   # default if not set
    python load_db.py

Reads data/raw/ with the same parser and checks as pipeline.py, creates the schema
if needed, and replaces this source's rows in one transaction: either everything is
loaded, or nothing changes. Safe to run repeatedly.
"""
import os
from pathlib import Path

import psycopg

from pipeline import DEUTSCHLAND, RENT_CSV, STICHTAG, load_rents, validate_rents

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///mietatlas")
SCHEMA_SQL = Path(__file__).parent / "db" / "schema.sql"
YEAR = int(STICHTAG[-4:])  # 15.05.2022 -> 2022

SOURCE = {
    "source_id": "zensus2022_4000W-0004",
    "name": "Zensus 2022, Tabelle 4000W-0004 (Durchschnittliche Nettokaltmiete)",
    "publisher": "Statistische Ämter des Bundes und der Länder",
    "url": "https://ergebnisse.zensus2022.de/datenbank/online/",
    "licence": "dl-de/by-2-0",
}
INDICATOR = {
    "indicator_id": "nettokaltmiete",
    "name": "Durchschnittliche Nettokaltmiete",
    "unit": "EUR/m²",
    "description": "Bestandsmieten aller vermieteten Wohnungen zum Zensusstichtag 15.05.2022",
}
FLAG_STATUS = {"e": "final"}  # Zensus quality flag -> status column
LAENDER = {
    "01": "Schleswig-Holstein", "02": "Hamburg", "03": "Niedersachsen", "04": "Bremen",
    "05": "Nordrhein-Westfalen", "06": "Hessen", "07": "Rheinland-Pfalz",
    "08": "Baden-Württemberg", "09": "Bayern", "10": "Saarland", "11": "Berlin",
    "12": "Brandenburg", "13": "Mecklenburg-Vorpommern", "14": "Sachsen",
    "15": "Sachsen-Anhalt", "16": "Thüringen",
}


def region_rows(rents: dict) -> list[tuple]:
    unknown = {a[:2] for a in rents} - set(LAENDER)
    assert not unknown, f"Kreise with unknown Land codes: {unknown}"
    rows = [("DE", "Deutschland", "bund", None)]
    rows += [(code, name, "land", "DE") for code, name in LAENDER.items()]
    rows += [(ags, r["name"], "kreis", ags[:2]) for ags, r in sorted(rents.items())]
    return rows


def observation_rows(rents: dict) -> list[tuple]:
    sid, iid = SOURCE["source_id"], INDICATOR["indicator_id"]
    # Germany-wide value from the same table (weighted by flats, not a mean of Kreise)
    rows = [("DE", iid, YEAR, DEUTSCHLAND, "final", sid)]
    rows += [(ags, iid, YEAR, r["miete"], FLAG_STATUS[r["flag"]], sid)
             for ags, r in sorted(rents.items())]
    return rows


def main() -> None:
    rents = load_rents(RENT_CSV)
    validate_rents(rents)

    # One transaction: committed when the block ends, rolled back on any error
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text())
        cur.execute(
            """INSERT INTO atlas.sources (source_id, name, publisher, url, licence)
               VALUES (%(source_id)s, %(name)s, %(publisher)s, %(url)s, %(licence)s)
               ON CONFLICT (source_id) DO UPDATE
               SET name = EXCLUDED.name, publisher = EXCLUDED.publisher,
                   url = EXCLUDED.url, licence = EXCLUDED.licence""",
            SOURCE,
        )
        cur.execute(
            """INSERT INTO atlas.indicators (indicator_id, name, unit, description)
               VALUES (%(indicator_id)s, %(name)s, %(unit)s, %(description)s)
               ON CONFLICT (indicator_id) DO UPDATE
               SET name = EXCLUDED.name, unit = EXCLUDED.unit,
                   description = EXCLUDED.description""",
            INDICATOR,
        )
        cur.executemany(
            """INSERT INTO atlas.regions (region_id, name, level, parent_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (region_id) DO UPDATE
               SET name = EXCLUDED.name, level = EXCLUDED.level,
                   parent_id = EXCLUDED.parent_id""",
            region_rows(rents),
        )
        # Full refresh of this source's values (official statistics get revised)
        cur.execute("DELETE FROM atlas.observations WHERE source_id = %s",
                    (SOURCE["source_id"],))
        with cur.copy(
            "COPY atlas.observations (region_id, indicator_id, year, value, status, source_id)"
            " FROM STDIN"
        ) as copy:
            for row in observation_rows(rents):
                copy.write_row(row)

        cur.execute("SELECT level, count(*) FROM atlas.regions GROUP BY level ORDER BY count(*)")
        regions = ", ".join(f"{n} {level}" for level, n in cur.fetchall())
        cur.execute("SELECT count(*) FROM atlas.observations WHERE source_id = %s",
                    (SOURCE["source_id"],))
        (n_obs,) = cur.fetchone()

    print(f"OK: regions ({regions}), {n_obs} observations from {SOURCE['source_id']}.")


if __name__ == "__main__":
    main()
