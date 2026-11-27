import re
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"PASS: {message}")


def location(config, name):
    pattern = rf"location\s+{re.escape(name)}\s*\{{([^{{}}]*)\}}"
    match = re.search(pattern, config)
    if match is None:
        raise SystemExit(f"FAIL: location {name}")
    return match.group(1)


def main():
    config = (LAB / "nginx/nginx.conf").read_text(encoding="utf-8")
    log = (LAB / "report/evidence/check-normal.txt").read_text(encoding="utf-8")

    docs = location(config, "^~ /docs/")
    require("alias /srv/lab1/docs/;" in docs and "autoindex off;" in docs,
            "/docs/ указывает на отдельный каталог без листинга")
    directory = LAB / "content/docs"
    require((directory / "guide.txt").is_file(), "в репозитории есть guide.txt")
    files = directory.rglob("*")
    require(all(not p.is_symlink() and not p.name.startswith(".") for p in files),
            "в каталоге docs нет скрытых файлов или символьных ссылок")
    require("File from alias directory: HTTP 200" in log,
            "в сохранённом прогоне открывается файл документации")

    for route in ("= /admin", "^~ /admin/"):
        admin = location(config, route)
        require('auth_basic "Lab1 admin";' in admin
                and "auth_basic_user_file /etc/nginx/lab1/.htpasswd;" in admin,
                f"{route} защищён Basic Auth")
    for path in ("/admin", "/admin/", "/admin/index.html"):
        require(f"Basic Auth without credentials: {path}: HTTP 401" in log
                and f"WWW-Authenticate header: {path}" in log,
                f"в сохранённом прогоне {path} запрашивает авторизацию")

    defaults = re.findall(r"server\s*\{([^{}]*default_server;[^{}]*)\}", config)
    require(len(defaults) == 2 and all("return 421;" in block for block in defaults),
            "у HTTP и HTTPS есть отдельные серверы по умолчанию с ответом 421")
    require("Unknown Host with valid notes.test TLS SNI: HTTP 421" in log
            and "Unknown HTTP virtual host: HTTP 421" in log
            and "Second host does not proxy the notes API: HTTP 404" in log,
            "сохранённый прогон подтверждает разделение виртуальных хостов")


if __name__ == "__main__":
    main()
