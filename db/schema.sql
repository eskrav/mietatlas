-- Database schema: regions and indicator values in long format.
-- Postgres 14+. Applied by load_db.py on every run; safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.sources (
    source_id   text PRIMARY KEY,               -- e.g. 'zensus2022_4000W-0004'
    name        text NOT NULL,
    publisher   text NOT NULL,
    url         text,
    licence     text NOT NULL
);

-- One table for all levels; the AGS hierarchy is stored in parent_id
CREATE TABLE IF NOT EXISTS atlas.regions (
    region_id   text PRIMARY KEY,               -- AGS ('11', '09162', ...); 'DE' for Germany
    name        text NOT NULL,
    level       text NOT NULL CHECK (level IN ('bund', 'land', 'kreis', 'gemeinde', 'wahlkreis')),
    parent_id   text REFERENCES atlas.regions (region_id),
    CHECK ((level = 'bund') = (parent_id IS NULL))
);

CREATE INDEX IF NOT EXISTS regions_parent_idx ON atlas.regions (parent_id);

CREATE TABLE IF NOT EXISTS atlas.indicators (
    indicator_id text PRIMARY KEY,              -- e.g. 'nettokaltmiete'
    name         text NOT NULL,
    unit         text NOT NULL,
    description  text
);

-- Ingested data: one long table, one row per region x indicator x year.
-- New indicators or years are new rows, not new columns or tables.
CREATE TABLE IF NOT EXISTS atlas.observations (
    region_id    text    NOT NULL REFERENCES atlas.regions (region_id),
    indicator_id text    NOT NULL REFERENCES atlas.indicators (indicator_id),
    year         integer NOT NULL CHECK (year BETWEEN 1990 AND 2100),
    value        numeric NOT NULL,
    status       text    NOT NULL CHECK (status IN ('final', 'provisional', 'estimate')),
    source_id    text    NOT NULL REFERENCES atlas.sources (source_id),
    loaded_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, indicator_id, year)
);

-- Map view: all regions for one indicator and year
CREATE INDEX IF NOT EXISTS observations_indicator_year_idx
    ON atlas.observations (indicator_id, year);
