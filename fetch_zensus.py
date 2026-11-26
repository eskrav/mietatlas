"""Fetch the Zensus 2022 rent table (4000W-0004, Kreise) from the Zensus database API.

The API needs a free account at https://ergebnisse.zensus2022.de. After logging in,
the API token is shown under "Webservice (API)". Pass it via an environment variable:

    export ZENSUS_API_TOKEN=...        # or ZENSUS_USERNAME and ZENSUS_PASSWORD
    python fetch_zensus.py

The API returns the CSV inside a ZIP archive; this script unpacks it, parses and checks
it with the same functions as pipeline.py, and only then replaces the file in data/raw/.
If anything looks wrong, the existing file is left untouched.
Only the standard library is used, so no extra dependency is needed.
"""
import io
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from pipeline import RENT_CSV, load_rents, validate_rents

API_BASE = os.environ.get("ZENSUS_API_BASE", "https://ergebnisse.zensus2022.de/api/rest/2020/")
TABLE = "4000W-0004"
REGIONAL_VARIABLE = "GEOLK4"  # Landkreise und kreisfreie Staedte, Gebietsstand 15.05.2022 (400)


def credentials() -> tuple[str, str]:
    token = os.environ.get("ZENSUS_API_TOKEN")
    if token:
        return token, ""  # the token goes in the username field, password stays empty
    user, pw = os.environ.get("ZENSUS_USERNAME"), os.environ.get("ZENSUS_PASSWORD")
    if not (user and pw):
        sys.exit("Set ZENSUS_API_TOKEN, or ZENSUS_USERNAME and ZENSUS_PASSWORD.")
    return user, pw


def fetch_table() -> str:
    user, pw = credentials()
    params = {
        "name": TABLE,
        "area": "all",
        "compress": "false",
        "format": "csv",
        "quality": "on",            # include quality flags (e.g. "e")
        "language": "de",
        "regionalvariable": REGIONAL_VARIABLE,
    }
    request = urllib.request.Request(
        API_BASE + "data/tablefile",
        data=urllib.parse.urlencode(params).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "username": user,
            "password": pw,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Zensus API returned HTTP {e.code}: {e.read()[:500]!r}")
    # Errors (wrong credentials, unknown table, ...) come back as JSON with a status message
    if "json" in content_type or raw.lstrip().startswith(b"{"):
        sys.exit(f"Zensus API did not return a table: {raw[:500].decode(errors='replace')}")
    # The table comes as a ZIP archive with a single CSV inside
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.endswith(".csv")]
            if len(names) != 1:
                sys.exit(f"expected one CSV in the ZIP archive, found {z.namelist()}")
            raw = z.read(names[0])
    return raw.decode("utf-8-sig")


def main() -> None:
    body = fetch_table()
    with tempfile.NamedTemporaryFile("w", suffix=".tmp", delete=False, encoding="utf-8",
                                     dir=RENT_CSV.parent) as tmp:
        tmp.write(body)
    try:
        new = load_rents(Path(tmp.name))
        validate_rents(new)  # same checks as the pipeline: 400 Kreise, AGS format, flags, range
    except (AssertionError, ValueError) as e:
        os.unlink(tmp.name)
        preview = "\n".join(body.splitlines()[:10])
        sys.exit(f"Downloaded table failed the checks, {RENT_CSV} left unchanged: {e}\n"
                 f"First lines of the download:\n{preview}")

    try:
        old = load_rents(RENT_CSV)
    except (AssertionError, ValueError, FileNotFoundError):
        old = None  # no previous file, or one in another layout (e.g. the website export)
    Path(tmp.name).replace(RENT_CSV)
    if old is None:
        print(f"OK: {len(new)} Kreise written to {RENT_CSV} (no comparable previous file).")
    else:
        changed = [a for a in new if a not in old or old[a]["miete"] != new[a]["miete"]]
        print(f"OK: {len(new)} Kreise written to {RENT_CSV}; {len(changed)} values new or changed.")


if __name__ == "__main__":
    main()
