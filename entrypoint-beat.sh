#!/bin/sh
set -e

echo "=== LicitaAI Beat ==="
echo "DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"

echo "Aguardando Postgres..."
python - <<'PY'
import os, time
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
    print("psycopg direto nao disponivel, pulando wait")
PY

echo "Iniciando Celery beat..."
exec celery -A config.celery beat \
    --loglevel=info
