#!/usr/bin/env bash
# Railway build script — runs during deploy, before the start command.
# Installs dependencies, collects static files, runs migrations, and seeds the database.

set -o errexit  # Exit on any error

cd backend

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed
