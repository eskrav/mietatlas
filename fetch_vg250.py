"""Fetch the BKG Kreis boundaries (VG250, Stand 31.12.2022) used by pipeline.py.

The BKG offers VG250 as open data, so no account is needed:

    python fetch_vg250.py

The archive (about 66 MB) is downloaded to a temporary file; only the Kreis layer
(VG250_KRS.*) is extracted and checked with the same function as pipeline.py before
it replaces data/raw/vg250/. If anything looks wrong, the existing files stay as they are.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from checks import DataCheckError
from pipeline import KREISE_SHP, load_kreise

URL = os.environ.get(
    "VG250_URL",
    "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_1231/2022/"
    "vg250_12-31.utm32s.shape.ebenen.zip",
)
LAYER = "VG250_KRS"
PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")  # all files that make up the shapefile
TARGET = KREISE_SHP.parent                          # data/raw/vg250


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as f:
            shutil.copyfileobj(response, f)
    except urllib.error.URLError as e:
        sys.exit(f"Download failed ({url}): {e}")


def extract_layer(archive: Path, dest: Path) -> None:
    """Extract only the Kreis layer, wherever it sits inside the archive."""
    with zipfile.ZipFile(archive) as z:
        wanted = {Path(n).name: n for n in z.namelist() if Path(n).stem == LAYER}
        missing = [LAYER + p for p in PARTS if LAYER + p not in wanted]
        if missing:
            sys.exit(f"{missing} not found in {archive.name}")
        for part in PARTS:
            (dest / (LAYER + part)).write_bytes(z.read(wanted[LAYER + part]))


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    # Temporary folder next to the target, so the final move stays on the same disk
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as tmp:
        tmp = Path(tmp)
        archive = tmp / "vg250.zip"
        download(URL, archive)
        extract_layer(archive, tmp)
        try:
            kreise = load_kreise(tmp / (LAYER + ".shp"))  # CRS, unique AGS, 400 Kreise
        except DataCheckError as e:
            sys.exit(f"Downloaded Kreis layer failed the checks, {TARGET} left unchanged: {e}")

        changed = [
            LAYER + p for p in PARTS
            if not (TARGET / (LAYER + p)).exists()
            or sha1(TARGET / (LAYER + p)) != sha1(tmp / (LAYER + p))
        ]
        for part in PARTS:
            os.replace(tmp / (LAYER + part), TARGET / (LAYER + part))

    status = "unchanged" if not changed else f"changed: {', '.join(changed)}"
    print(f"OK: {len(kreise)} Kreise written to {TARGET} ({status}).")


if __name__ == "__main__":
    main()
