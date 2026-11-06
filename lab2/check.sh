#!/bin/bash
# Лаба 2 — проверочный скрипт. Запускать из каталога lab2 (Git Bash / WSL,
# Docker Desktop должен быть запущен). Стек должен быть поднят:
#   docker compose up -d --build
set -e

echo "=== 1. Сборка плохого и хорошего образов ==="
docker build -f backend/Dockerfile.bad -t lab2-backend:bad ./backend || echo "bad-образ не собрался — см. скриншот выше"
docker build -f backend/Dockerfile.good -t lab2-backend:good ./backend

echo
echo "=== 2. Сравнение размера образов ==="
docker images lab2-backend --format "table {{.Tag}}\t{{.Size}}"

echo
echo "=== 3. Пользователь внутри хорошего образа ==="
docker run --rm lab2-backend:good whoami

echo
echo "=== 4. Время пересборки после правки одной строки кода ==="
echo "--- bad (без layer-кеша на код) ---"
echo "# touch" >> backend/app.py
time docker build -f backend/Dockerfile.bad -t lab2-backend:bad ./backend || echo "bad-образ не собрался — см. скриншот выше"
git checkout -- backend/app.py 2>/dev/null || sed -i '$ d' backend/app.py

echo "--- good (requirements.txt закеширован отдельно) ---"
echo "# touch" >> backend/app.py
time docker build -f backend/Dockerfile.good -t lab2-backend:good ./backend
git checkout -- backend/app.py 2>/dev/null || sed -i '$ d' backend/app.py

echo
echo "=== 5. Контейнеры стека подняты ==="
docker compose ps

echo
echo "=== 6. Персистентность тома: пишем запись, удаляем контейнер db, поднимаем заново ==="
curl -s -X POST http://127.0.0.1:8080/api/notes \
  -H "Content-Type: application/json" \
  -d '{"text":"persist-check"}'
echo
docker compose rm -sf db
docker compose up -d db
sleep 3
echo "Записи после пересоздания контейнера db:"
curl -s http://127.0.0.1:8080/api/notes

echo
echo "=== 7. Сетевая изоляция: frontend не видит db ==="
docker compose exec frontend sh -c "wget -T 3 -O- http://db:5432 2>&1; echo '--- ожидаем ошибку resolve/connect выше: frontend не на backend-net ---'"

echo
echo "Готово. Скриншоты вывода этого скрипта и docker compose ps — в отчёт."
