import argparse
import fcntl
import json
import os
import secrets
import shlex
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


STAR = Path(__file__).resolve().parent
LAB = STAR.parent
STATE_DIR = Path.home() / ".local/state/lab3-star"
STATE_FILE = STATE_DIR / "releases.json"
PROJECT = f"lab3-star-{os.getuid()}"
HTTP = build_opener(ProxyHandler({}))


def docker(*args, env=None, capture=False):
    print("$", shlex.join(("docker", *args)), flush=True)
    result = subprocess.run(("docker", *args), env=env, text=True,
                            stdout=subprocess.PIPE if capture else None, check=True)
    return result.stdout.strip() if capture else None


def read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"current": None, "previous": None}


def save_state(current, previous):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"current": current, "previous": previous}, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(STATE_FILE)


def image_id(ref):
    return docker("image", "inspect", "--format", "{{.Id}}", ref, capture=True)


def pin_image(tag, service):
    digest = image_id(tag)
    pinned = f"{PROJECT}-{service}:{digest.removeprefix('sha256:')}"
    docker("image", "tag", tag, pinned)
    return {"ref": pinned, "id": digest}


def request(base, path, note=None):
    req = Request(base + path)
    if note is not None:
        req = Request(base + path, json.dumps({"text": note}).encode(),
                      {"Content-Type": "application/json"})
    try:
        response = HTTP.open(req, timeout=4)
    except HTTPError as error:
        response = error
    except (URLError, TimeoutError):
        return 0, None, None
    with response:
        status = response.code
        image = response.headers.get("X-Backend-ID")
        try:
            body = json.load(response)
        except (ValueError, TimeoutError):
            body = None
    return status, body, image


def compose(release, password, *args, capture=False):
    env = dict(os.environ, DB_USER="lab3_star", DB_NAME="notes", DB_PASSWORD=password,
               BACKEND_IMAGE=release["backend"]["ref"], STAR_FRONTEND_IMAGE=release["frontend"]["ref"])
    return docker("compose", "-p", PROJECT, "--env-file", "/dev/null",
                  "-f", str(LAB / "docker-compose.ci.yml"), "-f", str(STAR / "compose.yml"),
                  *args, env=env, capture=capture)


def base_url(release, password):
    return "http://" + compose(release, password, "port", "frontend", "80", capture=True)


def apply(release, password):
    for service in ("backend", "frontend"):
        if image_id(release[service]["ref"]) != release[service]["id"]:
            raise RuntimeError(f"Изменился SHA образа {service}")

    compose(release, password, "up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "db")
    compose(release, password, "up", "-d", "--no-build", "--pull", "never", "--no-deps", "backend")
    # Nginx получает адрес backend при старте, поэтому frontend тоже пересоздаётся.
    compose(release, password, "up", "-d", "--no-build", "--pull", "never",
            "--no-deps", "--force-recreate", "frontend")
    for service in ("backend", "frontend"):
        container = compose(release, password, "ps", "-q", service, capture=True)
        actual = docker("inspect", "-f", "{{.Image}}", container, capture=True)
        if actual != release[service]["id"]:
            raise RuntimeError(f"Контейнер {service} запущен с другим образом")

    url = base_url(release, password)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, payload, image = request(url, "/api/health")
        if (status == release["health"] and image == release["backend"]["ref"]
                and isinstance(payload, dict) and payload.get("status") == release["marker"]):
            print(f"{release['name']}: GET /api/health → {status} {json.dumps(payload)}")
            return url
        time.sleep(1)
    raise RuntimeError(f"{release['name']}: ожидаемое состояние API не наступило")


def deploy(password):
    backend = f"{PROJECT}-backend:working"
    frontend = f"{PROJECT}-frontend:working"
    docker("build", "-f", str(LAB / "backend/Dockerfile.good"), "-t", backend, str(LAB / "backend"))
    docker("build", "-t", frontend, str(LAB / "frontend"))
    backend_image = pin_image(backend, "backend")
    release = {
        "name": "working-" + backend_image["id"][7:19],
        "backend": backend_image,
        "frontend": pin_image(frontend, "frontend"),
        "health": 200,
        "marker": "ok",
    }
    previous = read_state()["current"]
    apply(release, password)
    save_state(release, previous)
    return release


def break_release(password):
    working = read_state()["current"]
    if working is None or working["health"] != 200:
        raise RuntimeError("Сначала запусти рабочий релиз командой deploy")
    fault = f"{PROJECT}-backend:fault"
    docker("build", "-f", str(STAR / "Dockerfile.fault"), "--build-arg",
           f"BASE_IMAGE={working['backend']['ref']}", "-t", fault, str(STAR))
    backend_image = pin_image(fault, "backend")
    release = {
        "name": "fault-" + backend_image["id"][7:19],
        "backend": backend_image,
        "frontend": working["frontend"],
        "health": 503,
        "marker": "broken-demo",
    }
    apply(release, password)
    save_state(release, working)


def rollback(password):
    state = read_state()
    current = state["current"]
    if current is None:
        raise RuntimeError("Рабочий релиз ещё не сохранён")
    working = state["previous"] if current["health"] == 503 else current
    if working is None or working["health"] != 200:
        raise RuntimeError("В журнале нет рабочего релиза")

    started = time.monotonic()
    url = apply(working, password)
    print(f"ROLLBACK_SECONDS={time.monotonic() - started:.3f}")
    save_state(working, current if current != working else state["previous"])
    return url


def demo(password):
    working = deploy(password)
    url = base_url(working, password)
    code, note, _ = request(url, "/api/notes", "Запись до отката " + secrets.token_hex(4))
    if code != 201:
        raise RuntimeError(f"Не записалась контрольная заметка: HTTP {code}")
    db = compose(working, password, "ps", "-q", "db", capture=True)
    print(json.dumps(read_state(), indent=2))

    break_release(password)
    print(json.dumps(read_state(), indent=2))
    url = rollback(password)
    code, notes, _ = request(url, "/api/notes")
    if code != 200 or note not in notes:
        raise RuntimeError("После отката пропала контрольная заметка")
    if compose(working, password, "ps", "-q", "db", capture=True) != db:
        raise RuntimeError("Контейнер БД сменился")
    code, new_note, _ = request(url, "/api/notes", "Запись после отката")
    if code != 201:
        raise RuntimeError(f"После отката не записалась новая заметка: HTTP {code}")
    print(f"БД {db} на месте. Заметка {note['id']} читается, {new_note['id']} записалась. PASS")
    print(json.dumps(read_state(), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Демо отката для лабы 3")
    parser.add_argument("command", choices=("deploy", "status", "break", "rollback", "demo", "down"))
    args = parser.parse_args()

    os.umask(0o077)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "status":
            print(json.dumps(read_state(), indent=2))
            return
        secret_file = STATE_DIR / "db-password"
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(16), encoding="utf-8")
        password = secret_file.read_text(encoding="utf-8")
        if args.command == "deploy":
            deploy(password)
        elif args.command == "break":
            break_release(password)
        elif args.command == "rollback":
            rollback(password)
        elif args.command == "demo":
            demo(password)
        else:
            current = read_state()["current"]
            if current is None:
                current = {
                    "backend": {"ref": f"{PROJECT}-backend:working"},
                    "frontend": {"ref": f"{PROJECT}-frontend:working"},
                }
            compose(current, password, "down")


if __name__ == "__main__":
    main()
