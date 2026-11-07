import pytest

import app as app_module


def test_connect_db_rejects_missing_password(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        app_module.connect_db()


def test_connect_db_rejects_placeholder_password(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "CHANGE_ME")
    with pytest.raises(RuntimeError):
        app_module.connect_db()
