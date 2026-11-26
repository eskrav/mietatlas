"""Create the model tables and compute the example model in PostgreSQL.

    python run_model.py

Runs db/model_schema.sql (tables), db/model_kappung.sql (the model function) and
db/kappung_demo.sql (scenarios and example runs) against DATABASE_URL (the same
database load_db.py fills; run that first). Safe to run repeatedly.
"""
from pathlib import Path

import psycopg

from db import DATABASE_URL

DB_DIR = Path(__file__).parent / "db"
MODEL_FILES = ("model_schema.sql", "model_kappung.sql", "kappung_demo.sql")


def main(url: str = DATABASE_URL) -> None:
    # autocommit: the SQL files manage their own transactions (BEGIN ... COMMIT)
    with psycopg.connect(url, autocommit=True) as conn:
        for name in MODEL_FILES:
            conn.execute((DB_DIR / name).read_text())
        rows = conn.execute(
            "SELECT scenario_id, model_version FROM atlas.published_runs ORDER BY scenario_id"
        ).fetchall()
    print(f"OK: {len(rows)} published scenarios computed "
          f"({', '.join(f'{s} {v}' for s, v in rows)}).")


if __name__ == "__main__":
    main()
