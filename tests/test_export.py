"""Export of the published scenarios for the website (pipeline.load_scenarios_from_db)."""
import json

import pytest

from checks import DataCheckError
from db import load_scenarios_from_db
from pipeline import validate_scenarios
from zensus import RENT_CSV, load_rents


@pytest.fixture(scope="module")
def export(model_db):
    return load_scenarios_from_db(model_db)


def test_export_passes_checks(export):
    validate_scenarios(export, load_rents(RENT_CSV))


def test_scenarios_with_baseline_first_and_parameters(export):
    ids = [s["id"] for s in export["szenarien"]]
    assert ids == ["geltendes_recht", "kappung_10", "kappung_15_ueberall"]  # no draft
    base = export["szenarien"][0]
    assert base["basis"] and base["modellversion"] == "v0.2.0"
    assert base["parameter"]["rueckstand"] == 0.20  # latest run, not the earlier 15 % one


def test_berlin_values(export):
    # [highest EUR/m2, highest EUR/month, EUR/month at average growth (same in all scenarios)]
    assert export["werte"]["11000"] == {
        "geltendes_recht": [8.82, 617.0, 571.0],
        "kappung_10": [8.44, 591.0, 571.0],
        "kappung_15_ueberall": [8.82, 617.0, 571.0],
    }


def test_export_is_deterministic(model_db, export):
    again = load_scenarios_from_db(model_db)
    assert json.dumps(again) == json.dumps(export)


def test_missing_kreis_is_rejected(export):
    rents = load_rents(RENT_CSV)
    broken = {**export, "werte": {a: v for a, v in export["werte"].items() if a != "11000"}}
    with pytest.raises(DataCheckError, match="scenario values for 399 Kreise"):
        validate_scenarios(broken, rents)
