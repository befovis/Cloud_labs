from flask import request

from app import app


@app.before_request
def broken_health():
    if request.path == "/api/health":
        return {"status": "broken-demo"}, 503
