import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("DB_PASSWORD", "test-only-password")

import app as app_module  # noqa: E402  (import after env setup above)


class FakeCursor:
    """Stands in for a psycopg connection/cursor pair in tests.

    .execute() just remembers what it was asked to return next, so each
    test configures the fake with the rows/row it wants back.
    """

    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def execute(self, _query, _params=None):
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


def make_note_row(note_id=1, text="hello", when=None):
    return {
        "id": note_id,
        "text": text,
        "created_at": when or datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def fake_db(monkeypatch):
    """Patch app.connect_db; tests set .rows / .one on the returned fake."""
    fake = FakeCursor()
    monkeypatch.setattr(app_module, "connect_db", lambda: fake)
    return fake
