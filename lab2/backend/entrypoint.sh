#!/bin/sh
set -e

flask --app app init-db
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --access-logfile - app:app
