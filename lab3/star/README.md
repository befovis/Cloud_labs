# Откат релиза

Для опыта используется отдельный Compose-проект с именем `lab3-star-<UID>`. После сборки сохраняются SHA обоих Docker-образов. При запуске сверяются сохранённые SHA и образы контейнеров. Список релизов хранится в `~/.local/state/lab3-star/releases.json`.

## Полный прогон

Из корня репозитория на Ubuntu или в WSL с Docker Compose от 2.24.4

```bash
set -o pipefail
python3 -u lab3/star/manage.py demo 2>&1 | tee lab3-star.log
```

Сначала поднимается рабочая версия, проверяется HTTP 200 и сохраняется заметка. Затем запускается отдельный образ бэкенда, в котором проверка здоровья возвращает `503 broken-demo`. После отката скрипт проверяет HTTP 200, читает сохранённую заметку и добавляет новую. ID контейнера PostgreSQL сверяется до и после опыта.

## По шагам

```bash
python3 lab3/star/manage.py deploy
python3 lab3/star/manage.py status
python3 lab3/star/manage.py break
python3 lab3/star/manage.py rollback
```

`ROLLBACK_SECONDS` показывает время от начала применения сохранённого релиза до успешного ответа API. Для остановки стенда есть `python3 lab3/star/manage.py down`. Том с тестовыми заметками сохраняется.
