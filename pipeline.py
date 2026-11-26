"""Build the Kreis-level rent dataset for the map.

Steps: read the Zensus 2022 rents from the PostgreSQL database (filled from data/raw/
by load_db.py) and the BKG VG250 Kreis boundaries from data/raw/, validate both,
join them on the 5-digit Amtlicher Gemeindeschluessel (AGS),
simplify the boundaries for the web, and write a GeoJSON for the map. Also export
the published scenarios of the example model (computed by run_model.py).
Every check raises an error, so a broken input stops the build.
"""
import csv
import json
import os
import statistics
import sys
from pathlib import Path

import geopandas as gpd
import psycopg
import shapely

RAW = Path("data/raw")
OUT = Path("docs/data")  # GitHub Pages serves the docs/ folder

RENT_CSV = RAW / "zensus2022_4000W-0004_nettokaltmiete_kreise.csv"
KREISE_SHP = RAW / "vg250" / "VG250_KRS.shp"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///mietatlas")

EXPECTED_KREISE = 400          # Gebietsstand 2022: 294 Landkreise + 106 kreisfreie Staedte
STICHTAG = "15.05.2022"        # census reference date in the Zensus table
YEAR = int(STICHTAG[-4:])      # year under which the values are stored in the database
INDICATOR_ID = "nettokaltmiete"
KNOWN_FLAGS = {"e"}            # quality flags we know how to handle ("e" = final value)
PLAUSIBLE_RANGE = (2.0, 20.0)  # EUR/m2; outside this, something likely went wrong in parsing
SIMPLIFY_TOLERANCE_M = 300     # metres, applied in UTM32 before converting to WGS84
# Colour classes: equal intervals over a trimmed range. The range runs from the 2nd to the
# 98th percentile, so a few extreme Kreise (e.g. Munich) don't stretch every class; values
# outside it fall into the two open end classes. Works unchanged for any indicator.
N_CLASSES = 6
TRIM_PERCENTILES = (2, 98)
# Germany-wide value from the same table at "Deutschland" level. It is weighted by the
# number of rented flats, so it is NOT the mean of the 400 Kreis values. In the future, 
# consider not hardcoding this, but rather reading it from the relevant Zensus table.
DEUTSCHLAND = 7.28


class DataCheckError(Exception):
    """A data check failed; the build stops with this message."""


def check(condition: bool, message: str) -> None:
    # Explicit check instead of assert: asserts are skipped when Python runs with -O
    if not condition:
        raise DataCheckError(message)


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


def validate_scenarios(export: dict, rents: dict) -> None:
    """Every Kreis on the map needs both values for every published scenario."""
    ids = [s["id"] for s in export["szenarien"]]
    check(ids, "no published scenarios in the database")
    check(sum(s["basis"] for s in export["szenarien"]) == 1, "expected exactly one baseline scenario")
    check(set(export["werte"]) == set(rents),
          f"scenario values for {len(export['werte'])} Kreise, expected {len(rents)}")
    gaps = [(a, sid) for a, row in export["werte"].items() for sid in ids
            if sid not in row or None in row[sid]]
    check(not gaps, f"missing scenario values: {gaps[:5]}")
    bad = [a for a, row in export["werte"].items() for v in row.values() if min(v) <= 0]
    check(not bad, f"non-positive scenario values: {bad[:5]}")


def load_kreise(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    # GF 4 = land areas; GF 2 = water areas (e.g. coastal waters, Bodensee)
    gdf = gdf[gdf["GF"] == 4][["AGS", "GEN", "BEZ", "geometry"]].reset_index(drop=True)
    check(gdf.crs.to_epsg() == 25832, f"unexpected CRS {gdf.crs}")
    check(gdf["AGS"].is_unique, "duplicate AGS in VG250 Kreis layer")
    check(len(gdf) == EXPECTED_KREISE, f"expected {EXPECTED_KREISE} Kreise in VG250, got {len(gdf)}")
    return gdf


def validate_join(rents: dict, kreise: gpd.GeoDataFrame) -> None:
    """Both sides must match exactly, otherwise Kreise vanish from the map silently."""
    only_rents = set(rents) - set(kreise["AGS"])
    only_geo = set(kreise["AGS"]) - set(rents)
    check(not only_rents and not only_geo, (
        f"AGS mismatch: only in Zensus {sorted(only_rents)}, only in VG250 {sorted(only_geo)}"
    ))


def simplify(kreise: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Coverage simplification keeps shared borders identical, so no gaps or
    overlaps appear between neighbouring Kreise (per-polygon simplify would)."""
    out = kreise.copy()
    out["geometry"] = shapely.coverage_simplify(out.geometry.values, SIMPLIFY_TOLERANCE_M)
    check(out.geometry.is_valid.all(), "simplification produced invalid geometries")
    return out.to_crs(4326)


def equal_interval_breaks(values, n_classes: int, trim: tuple) -> list:
    """n_classes - 1 class boundaries: the trimmed range [p_lo, p_hi] is split into
    n_classes - 2 equal steps, leaving one open class below and one above it."""
    lo, hi = values.quantile([trim[0] / 100, trim[1] / 100])
    step = (hi - lo) / (n_classes - 2)
    return [round(float(lo + i * step), 2) for i in range(n_classes - 1)]


def main() -> None:
    rents, deutschland = load_rents_from_db()
    validate_values(rents)
    kreise = load_kreise(KREISE_SHP)
    validate_join(rents, kreise)

    kreise["miete"] = kreise["AGS"].map(lambda a: rents[a]["miete"])
    kreise["land"] = kreise["AGS"].str[:2]  # first two AGS digits = Bundesland
    gdf = simplify(kreise)

    OUT.mkdir(parents=True, exist_ok=True)
    gdf["name"] = gdf["AGS"].map(lambda a: rents[a]["name"])  # official Zensus name
    gdf["rang"] = gdf["miete"].rank(ascending=False, method="min").astype(int)
    gdf[["AGS", "name", "BEZ", "land", "miete", "rang", "geometry"]].to_file(
        OUT / "kreise_mieten.geojson", driver="GeoJSON",
        COORDINATE_PRECISION=4)  # ~10 m, plenty for a national map
    # Laender outlines for orientation, dissolved from the (already shared) Kreis borders
    gdf.dissolve(by="land")[["geometry"]].reset_index().to_file(
        OUT / "laender.geojson", driver="GeoJSON", COORDINATE_PRECISION=4)

    values = sorted(r["miete"] for r in rents.values())
    breaks = equal_interval_breaks(gdf["miete"], N_CLASSES, TRIM_PERCENTILES)
    # every class must contain at least one Kreis, otherwise a legend entry is empty
    edges = [-float("inf"), *breaks, float("inf")]
    counts = [sum(lo <= v < hi for v in values) for lo, hi in zip(edges, edges[1:])]
    check(all(counts), f"empty colour class: {counts}")
    summary = {
        "quelle": "Zensus 2022, Tabelle 4000W-0004; Geometrie: BKG VG250 (31.12.2022)",
        "stichtag": STICHTAG,
        "anzahl_kreise": len(rents),
        "min": values[0],
        "max": values[-1],
        "median": round(statistics.median(values), 2),
        "deutschland": deutschland,
        "klassengrenzen": breaks,
        "kreise_je_klasse": counts,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    scenarios = load_scenarios_from_db()
    validate_scenarios(scenarios, rents)
    (OUT / "szenarien.json").write_text(
        json.dumps(scenarios, ensure_ascii=False, separators=(",", ":")))
    size_kb = (OUT / "kreise_mieten.geojson").stat().st_size // 1024
    print(f"OK: {len(gdf)} Kreise written ({size_kb} KB). "
          f"Range {values[0]}-{values[-1]} EUR/m2, median {summary['median']}. "
          f"{len(scenarios['szenarien'])} scenarios exported.")


if __name__ == "__main__":
    main()
