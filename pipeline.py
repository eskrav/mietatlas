"""Build the Kreis-level rent dataset for the map.

Steps: read the Zensus 2022 rents from the PostgreSQL database (filled from data/raw/
by load_db.py) and the BKG VG250 Kreis boundaries from data/raw/, validate both,
join them on the 5-digit Amtlicher Gemeindeschluessel (AGS),
simplify the boundaries for the web, and write a GeoJSON for the map. Also export
the published scenarios of the example model (computed by run_model.py).
Every check raises an error, so a broken input stops the build.

Shared pieces live in checks.py (data checks), zensus.py (the rent table) and db.py
(database reads); this module holds the geo processing and the export.
"""
import json
import statistics
from pathlib import Path

import geopandas as gpd
import shapely

from checks import check
from db import N_RENT_VALUES, load_rents_from_db, load_scenarios_from_db
from zensus import EXPECTED_KREISE, RAW, STICHTAG, validate_values

OUT = Path("docs/data")  # GitHub Pages serves the docs/ folder
KREISE_SHP = RAW / "vg250" / "VG250_KRS.shp"

SIMPLIFY_TOLERANCE_M = 300     # metres, applied in UTM32 before converting to WGS84
# Colour classes: equal intervals over a trimmed range. The range runs from the 2nd to the
# 98th percentile, so a few extreme Kreise (e.g. Munich) don't stretch every class; values
# outside it fall into the two open end classes. Works unchanged for any indicator.
N_CLASSES = 6
TRIM_PERCENTILES = (2, 98)


def validate_scenarios(export: dict, rents: dict) -> None:
    """Every Kreis on the map needs every value for every published scenario."""
    ids = [s["id"] for s in export["szenarien"]]
    check(ids, "no published scenarios in the database")
    check(sum(s["basis"] for s in export["szenarien"]) == 1, "expected exactly one baseline scenario")
    check(set(export["werte"]) == set(rents),
          f"scenario values for {len(export['werte'])} Kreise, expected {len(rents)}")
    gaps = [(a, sid) for a, row in export["werte"].items() for sid in ids
            if sid not in row or None in row[sid]]
    check(not gaps, f"missing scenario values: {gaps[:5]}")
    bad = [a for a, row in export["werte"].items() for v in row.values()
           if min(v[:N_RENT_VALUES]) <= 0]
    check(not bad, f"non-positive scenario rents: {bad[:5]}")


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
