"""Build the Kreis-level rent dataset for the map.

Steps: load the Zensus 2022 rent table and the BKG VG250 Kreis boundaries,
validate both, join them on the 5-digit Amtlicher Gemeindeschluessel (AGS),
simplify the boundaries for the web, and write a GeoJSON for the map.
Every check raises an error, so a broken input stops the build.
"""
import csv
import json
import statistics
from pathlib import Path

import geopandas as gpd
import shapely

RAW = Path("data/raw")
OUT = Path("docs/data")  # GitHub Pages serves the docs/ folder

RENT_CSV = RAW / "zensus2022_4000W-0004_nettokaltmiete_kreise.csv"
KREISE_SHP = RAW / "vg250" / "VG250_KRS.shp"

EXPECTED_KREISE = 400          # Gebietsstand 2022: 294 Landkreise + 106 kreisfreie Staedte
STICHTAG = "15.05.2022"        # census reference date in the Zensus table
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


def load_rents(path: Path) -> dict:
    """Parse the Zensus CSV export. AGS stays a string to keep leading zeros."""
    rents = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f, delimiter=";"):
            # data rows start with the reference date; header and footer rows don't
            if len(row) != 5 or row[0] != STICHTAG:
                continue
            _, ags, name, value, flag = row
            assert ags not in rents, f"duplicate AGS in Zensus table: {ags}"
            rents[ags] = {
                "name": name,
                "miete": float(value.replace(",", ".")),  # German decimal comma
                "flag": flag,
            }
    return rents


def validate_rents(rents: dict) -> None:
    assert len(rents) == EXPECTED_KREISE, f"expected {EXPECTED_KREISE} Kreise, got {len(rents)}"
    bad_ags = [a for a in rents if not (len(a) == 5 and a.isdigit())]
    assert not bad_ags, f"malformed AGS codes: {bad_ags[:5]}"
    flags = {r["flag"] for r in rents.values()}
    assert flags <= KNOWN_FLAGS, f"unknown quality flags: {flags - KNOWN_FLAGS}"
    lo, hi = PLAUSIBLE_RANGE
    odd = {a: r["miete"] for a, r in rents.items() if not lo <= r["miete"] <= hi}
    assert not odd, f"implausible rent values: {odd}"


def load_kreise(path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    # GF 4 = land areas; GF 2 = water areas (e.g. coastal waters, Bodensee)
    gdf = gdf[gdf["GF"] == 4][["AGS", "GEN", "BEZ", "geometry"]].reset_index(drop=True)
    assert gdf.crs.to_epsg() == 25832, f"unexpected CRS {gdf.crs}"
    assert gdf["AGS"].is_unique, "duplicate AGS in VG250 Kreis layer"
    assert len(gdf) == EXPECTED_KREISE, f"expected {EXPECTED_KREISE} Kreise in VG250, got {len(gdf)}"
    return gdf


def validate_join(rents: dict, kreise: gpd.GeoDataFrame) -> None:
    """Both sides must match exactly, otherwise Kreise vanish from the map silently."""
    only_rents = set(rents) - set(kreise["AGS"])
    only_geo = set(kreise["AGS"]) - set(rents)
    assert not only_rents and not only_geo, (
        f"AGS mismatch: only in Zensus {sorted(only_rents)}, only in VG250 {sorted(only_geo)}"
    )


def simplify(kreise: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Coverage simplification keeps shared borders identical, so no gaps or
    overlaps appear between neighbouring Kreise (per-polygon simplify would)."""
    out = kreise.copy()
    out["geometry"] = shapely.coverage_simplify(out.geometry.values, SIMPLIFY_TOLERANCE_M)
    assert out.geometry.is_valid.all(), "simplification produced invalid geometries"
    return out.to_crs(4326)


def equal_interval_breaks(values, n_classes: int, trim: tuple) -> list:
    """n_classes - 1 class boundaries: the trimmed range [p_lo, p_hi] is split into
    n_classes - 2 equal steps, leaving one open class below and one above it."""
    lo, hi = values.quantile([trim[0] / 100, trim[1] / 100])
    step = (hi - lo) / (n_classes - 2)
    return [round(float(lo + i * step), 2) for i in range(n_classes - 1)]


def main() -> None:
    rents = load_rents(RENT_CSV)
    validate_rents(rents)
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
    assert all(counts), f"empty colour class: {counts}"
    summary = {
        "quelle": "Zensus 2022, Tabelle 4000W-0004; Geometrie: BKG VG250 (31.12.2022)",
        "stichtag": STICHTAG,
        "anzahl_kreise": len(rents),
        "min": values[0],
        "max": values[-1],
        "median": round(statistics.median(values), 2),
        "deutschland": DEUTSCHLAND,
        "klassengrenzen": breaks,
        "kreise_je_klasse": counts,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    size_kb = (OUT / "kreise_mieten.geojson").stat().st_size // 1024
    print(f"OK: {len(gdf)} Kreise written ({size_kb} KB). "
          f"Range {values[0]}-{values[-1]} EUR/m2, median {summary['median']}.")


if __name__ == "__main__":
    main()
