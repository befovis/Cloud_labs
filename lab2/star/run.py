import json
import math
import os
import secrets
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


LAB = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


def run(*args, env=None, capture=False, check=True):
    print("$", shlex.join(args), flush=True)
    result = subprocess.run(args, env=env, text=True, capture_output=capture, check=False)
    if result.returncode and result.stderr:
        print(result.stderr, end="")
    if check:
        result.check_returncode()
    return result.stdout.strip() if capture else None


def request(url, note=None):
    req = Request(url)
    if note is not None:
        req = Request(url, json.dumps({"text": note}).encode(),
                      {"Content-Type": "application/json"})
    started = time.monotonic()
    try:
        with HTTP.open(req, timeout=45) as response:
            status = response.status
            body = json.load(response)
    except HTTPError as error:
        error.close()
        status, body = error.code, None
    except (URLError, TimeoutError):
        status, body = 0, None
    return status, body, time.monotonic() - started


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_recovery(compose, base):
    url = base + "/api/notes"
    code, note, _ = request(url, "Запись до перезапуска PostgreSQL")
    require(code == 201, f"Не удалось сохранить заметку: HTTP {code}")
    db_id = compose("ps", "-q", "db", capture=True)
    before = int(run("docker", "inspect", "-f", "{{.RestartCount}}", db_id, capture=True))
    print(f"До остановки: db={db_id}, RestartCount={before}, заметка={note['id']}")
    time.sleep(10)
    compose("exec", "-T", "--user", "postgres", "db", "sh", "-c", "kill -QUIT 1",
            check=False)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        count = int(run("docker", "inspect", "-f", "{{.RestartCount}}", db_id, capture=True))
        code, _, _ = request(base + "/api/health")
        print(f"RestartCount={count}, HTTP {code}")
        if count > before and code == 200:
            require(compose("ps", "-q", "db", capture=True) == db_id, "Контейнер БД сменился")
            print(f"PostgreSQL восстановился: db={db_id}, RestartCount={count}, HTTP 200")
            return note
        time.sleep(1)
    raise RuntimeError("PostgreSQL не восстановился за 60 секунд")


def counters(compose):
    output = compose("exec", "-T", "backend", "cat", "/sys/fs/cgroup/cpu.stat",
                     "/sys/fs/cgroup/memory.events", capture=True)
    values = dict(line.split() for line in output.splitlines())
    return {key: int(values[key]) for key in ("nr_throttled", "throttled_usec", "oom_kill")}


def sample(compose, name, base, route, total, concurrency):
    before = counters(compose)
    services = compose("ps", "-q", capture=True).splitlines()
    print(f"\n{name}: {total} запросов, параллельно {concurrency}")
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = [pool.submit(request, base + route) for _ in range(total)]
        run("docker", "stats", "--no-stream", "--format",
            "{{.Name}}  CPU={{.CPUPerc}}  MEM={{.MemUsage}}", *services)
        results = [future.result() for future in pending]
    after = counters(compose)
    statuses = [status for status, _, _ in results]
    times = sorted(elapsed for _, _, elapsed in results)
    all_ok = all(status == 200 for status in statuses)
    print(json.dumps({
        "profile": name,
        "before": before,
        "after": after,
        "http": {status: statuses.count(status) for status in sorted(set(statuses))},
        "p95_ms": round(times[math.ceil(total * 0.95) - 1] * 1000, 1),
        "all_200": all_ok,
    }))
    return before, after, all_ok


def restart_app(compose, env, cpu, memory):
    env.update(LAB2_CPU=cpu, LAB2_MEMORY=memory)
    print(f"\nЛимиты backend: {cpu} CPU / {memory}")
    for service in ("backend", "frontend"):
        compose("up", "-d", "--no-deps", "--force-recreate", "--no-build", "--wait",
                "--wait-timeout", "90", service)
    return "http://" + compose("port", "frontend", "80", capture=True)


def main():
    project = "lab2-star-" + secrets.token_hex(4)
    env = dict(os.environ, DB_USER="lab2_star", DB_NAME="notes",
               DB_PASSWORD=secrets.token_hex(16), LAB2_CPU="1.0", LAB2_MEMORY="512m")

    def compose(*args, capture=False, check=True):
        return run("docker", "compose", "-p", project, "--env-file", "/dev/null",
                   "-f", str(LAB / "docker-compose.yml"), "-f", str(LAB / "star/compose.yml"),
                   *args, env=env, capture=capture, check=check)

    compose("config", "--quiet")
    try:
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "120")
        base = "http://" + compose("port", "frontend", "80", capture=True)
        note = check_recovery(compose, base)

        base = restart_app(compose, env, "0.10", "512m")
        before, after, all_ok = sample(compose, "cpu-0.10", base, "/api/lab/cpu", 80, 8)
        require(all_ok, "Часть запросов CPU не получила HTTP 200")
        require(after["nr_throttled"] > before["nr_throttled"], "Не зафиксирован CPU throttling")

        base = restart_app(compose, env, "1.0", "96m")
        before, after, all_ok = sample(compose, "memory-96m", base, "/api/lab/memory", 8, 1)
        compose("logs", "--no-color", "--tail", "25", "backend")
        require(after["oom_kill"] > before["oom_kill"], "Не зафиксирован OOM kill")
        require(not all_ok, "При OOM ожидалась ошибка хотя бы одного запроса")

        base = restart_app(compose, env, "1.0", "512m")
        _, _, all_ok = sample(compose, "cpu-stable", base, "/api/lab/cpu", 80, 8)
        require(all_ok, "CPU при рабочих лимитах: есть ошибки HTTP")
        before, after, all_ok = sample(compose, "memory-stable", base, "/api/lab/memory", 8, 1)
        require(all_ok and after["oom_kill"] == before["oom_kill"],
                "Память при рабочих лимитах: есть ошибки или OOM")

        code, notes, _ = request(base + "/api/notes")
        require(code == 200 and note in notes, "Заметка, сохранённая до перезапуска, пропала")
        code, new_note, _ = request(base + "/api/notes", "Запись после замеров")
        require(code == 201, f"Новая заметка не записалась: HTTP {code}")
        print(f"Сохранена заметка {note['id']}, новая заметка {new_note['id']} записана. PASS")
    except Exception:
        compose("ps", check=False)
        compose("logs", "--no-color", "--tail", "40", check=False)
        raise
    finally:
        compose("down", "--volumes", check=False)


if __name__ == "__main__":
    main()
