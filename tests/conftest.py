"""Shared fixtures.

The database tests use TEST_DATABASE_URL (default: postgresql:///mietatlas_test).
Without a reachable database they are skipped, unless REQUIRE_DB_TESTS=1 (as in
GitHub Actions), in which case they fail instead.
"""
import os

import psycopg
import pytest

URL = os.environ.get("TEST_DATABASE_URL", "postgresql:///mietatlas_test")


@pytest.fixture(scope="module")
def db():
    try:
        psycopg.connect(URL).close()
    except psycopg.OperationalError as e:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail(f"test database not reachable: {e}")
        pytest.skip(f"no test database at {URL} (createdb mietatlas_test to run these)")
    return URL


@pytest.fixture(scope="module")
def model_db(db):
    """Test database with the real data loaded and the example model computed."""
    import load_db
    import run_model

    load_db.main(db)
    run_model.main(db)
    return db
