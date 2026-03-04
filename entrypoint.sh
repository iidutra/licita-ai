#!/bin/sh
set -e

echo "=== LicitaAI Startup ==="
echo "PORT=$PORT"
echo "DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"

echo "Aguardando Postgres..."
python - <<'PY'
import os, time, sys
try:
    import psycopg
    from urllib.parse import urlparse
    u = urlparse(os.environ["DATABASE_URL"])
    for i in range(30):
        try:
            conn = psycopg.connect(
                host=u.hostname, port=u.port or 5432,
                dbname=u.path.lstrip("/"),
                user=u.username, password=u.password,
                connect_timeout=3,
            )
            conn.close()
            print("Postgres OK")
            break
        except Exception:
            print(f"Tentativa {i+1}/30...")
            time.sleep(2)
    else:
        raise SystemExit("Postgres nao ficou pronto a tempo")
except ImportError:
    import django.db
    print("psycopg direto nao disponivel, pulando wait")
PY

echo "Rodando migrate..."
python manage.py migrate --noinput

echo "Coletando static files..."
python manage.py collectstatic --noinput || true

echo "Iniciando gunicorn na porta $PORT..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
