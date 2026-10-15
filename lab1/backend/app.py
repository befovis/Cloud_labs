import os
from pathlib import Path

import click
import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=False)

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


def connect_db():
    """Open a new TCP connection to PostgreSQL."""
    password = os.getenv("DB_PASSWORD", "")
    if not password or password == "CHANGE_ME":
        raise RuntimeError("Set DB_PASSWORD in .env before starting.")
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "lab0_notes"),
        user=os.getenv("DB_USER", "lab0_user"),
        password=password,
        connect_timeout=5,
        row_factory=dict_row,
    )


def note_json(row):
    return {
        "id": row["id"],
        "text": row["text"],
        "created_at": row["created_at"].isoformat(),
    }


@app.cli.command("init-db")
def init_db():
    """Create the notes table without deleting existing data."""
    try:
        with connect_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id BIGINT GENERATED ALWAYS AS IDENTITY
                        PRIMARY KEY,
                    text TEXT NOT NULL
                        CHECK (char_length(trim(text))
                            BETWEEN 1 AND 500),
                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT CURRENT_TIMESTAMP
                )
            """)
    except (psycopg.Error, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Database initialized: table notes is ready.")


@app.get("/api/health")
def health():
    with connect_db() as conn:
        conn.execute("SELECT 1").fetchone()
    return jsonify(status="ok", database="ok")


@app.get("/api/notes")
def list_notes():
    with connect_db() as conn:
        rows = conn.execute("""
            SELECT id, text, created_at
            FROM notes
            ORDER BY id DESC
        """).fetchall()
    return jsonify([note_json(row) for row in rows])


@app.post("/api/notes")
def create_note():
    data = request.get_json(silent=True)
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str):
        return jsonify(error="Передайте поле text как строку."), 400
    text = text.strip()
    if not 1 <= len(text) <= 500 or "\x00" in text:
        return jsonify(error="Введите текст от 1 до 500 символов."), 400
    with connect_db() as conn:
        row = conn.execute("""
            INSERT INTO notes (text)
            VALUES (%s)
            RETURNING id, text, created_at
        """, (text,)).fetchone()
    # Leaving the connection context commits the transaction.
    return jsonify(note_json(row)), 201


@app.errorhandler(psycopg.Error)
def database_error(exc):
    app.logger.error("Database error: %s", type(exc).__name__)
    return jsonify(
        error="Ошибка PostgreSQL. Проверьте сервис, .env и init-db."
    ), 503


@app.errorhandler(RuntimeError)
@app.errorhandler(ValueError)
def configuration_error(exc):
    app.logger.error("Configuration error: %s", type(exc).__name__)
    return jsonify(error="Проверьте DB_PASSWORD и DB_PORT в .env."), 500


@app.errorhandler(413)
def request_too_large(exc):
    return jsonify(error="Слишком большой запрос."), 413


@app.errorhandler(404)
def not_found(exc):
    return jsonify(error="API endpoint not found."), 404


@app.after_request
def api_no_cache(response):
    response.headers["X-Backend-ID"] = os.getenv("INSTANCE_ID", "unset")
    if request.path == "/api" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
