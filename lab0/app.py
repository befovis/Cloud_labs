import os
from pathlib import Path

import click
import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from psycopg.rows import dict_row

load_dotenv(Path(__file__).with_name(".env"))
app = Flask(__name__)
app.json.ensure_ascii = False


def connect_db():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "lab0_notes"),
        user=os.getenv("DB_USER", "lab0_user"),
        password=os.environ["DB_PASSWORD"],
        row_factory=dict_row,
        connect_timeout=5,
    )


@app.cli.command("init-db")
def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                text VARCHAR(500) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    click.echo("Таблица notes готова")


@app.get("/")
def index():
    return render_template("index.html")


def as_json(note):
    return {
        "id": note["id"],
        "text": note["text"],
        "created_at": note["created_at"].isoformat(),
    }


@app.route("/api/notes", methods=["GET", "POST"])
def notes():
    if request.method == "GET":
        with connect_db() as conn:
            rows = conn.execute(
                "SELECT id, text, created_at FROM notes ORDER BY id DESC"
            ).fetchall()
        return jsonify([as_json(row) for row in rows])

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        return jsonify(error="Передайте текст записи"), 400
    text = data["text"].strip()
    if not 1 <= len(text) <= 500:
        return jsonify(error="Введите от 1 до 500 символов"), 400

    with connect_db() as conn:
        row = conn.execute(
            "INSERT INTO notes (text) VALUES (%s) "
            "RETURNING id, text, created_at",
            (text,),
        ).fetchone()
    return jsonify(as_json(row)), 201


@app.errorhandler(psycopg.Error)
def database_error(error):
    app.logger.exception("Ошибка PostgreSQL")
    return jsonify(error="Нет доступа к базе. Проверьте PostgreSQL и .env"), 503
