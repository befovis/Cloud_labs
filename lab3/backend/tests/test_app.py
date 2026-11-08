from conftest import make_note_row


# --- validation happens before any DB call, so no fake_db needed here ---


def test_create_note_rejects_missing_text(client):
    response = client.post("/api/notes", json={})
    assert response.status_code == 400
    assert "text" in response.get_json()["error"].lower() or response.get_json()["error"]


def test_create_note_rejects_non_string_text(client):
    response = client.post("/api/notes", json={"text": 123})
    assert response.status_code == 400


def test_create_note_rejects_blank_text(client):
    response = client.post("/api/notes", json={"text": "   "})
    assert response.status_code == 400


def test_create_note_rejects_too_long_text(client):
    response = client.post("/api/notes", json={"text": "x" * 501})
    assert response.status_code == 400


def test_request_too_large_returns_413(client):
    huge_payload = "x" * (20 * 1024)  # over MAX_CONTENT_LENGTH (16 KiB)
    response = client.post(
        "/api/notes",
        data=huge_payload,
        content_type="application/json",
    )
    assert response.status_code == 413
    assert response.get_json()["error"]


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["error"]


# --- these exercise the success paths with a fake DB connection ---


def test_create_note_success(client, fake_db):
    fake_db._one = make_note_row(note_id=1, text="hello")
    response = client.post("/api/notes", json={"text": "hello"})
    assert response.status_code == 201
    body = response.get_json()
    assert body["id"] == 1
    assert body["text"] == "hello"
    assert "created_at" in body


def test_list_notes_returns_serialized_rows(client, fake_db):
    fake_db._rows = [
        make_note_row(note_id=2, text="второй"),
        make_note_row(note_id=1, text="первый"),
    ]
    response = client.get("/api/notes")
    assert response.status_code == 200
    body = response.get_json()
    assert [note["id"] for note in body] == [2, 1]


def test_health_ok(client, fake_db):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}


def test_backend_id_header_reflects_instance_id(client, fake_db, monkeypatch):
    monkeypatch.setenv("INSTANCE_ID", "backend-test")
    fake_db._rows = []
    response = client.get("/api/notes")
    assert response.headers.get("X-Backend-ID") == "backend-test"


def test_notes_responses_are_not_cached(client, fake_db):
    fake_db._rows = []
    response = client.get("/api/notes")
    assert response.headers.get("Cache-Control") == "no-store"
