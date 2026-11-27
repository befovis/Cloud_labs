import hashlib
import time

from app import app


@app.get("/api/lab/cpu")
def cpu():
    hashlib.pbkdf2_hmac("sha256", b"lab2", b"load", 150_000)
    return {"status": "ok"}


@app.get("/api/lab/memory")
def memory():
    data = bytearray(160 * 1024 * 1024)
    data[::4096] = b"\x01" * (len(data) // 4096)
    time.sleep(0.75)
    return {"allocated_mib": len(data) // (1024 * 1024)}
