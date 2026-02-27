.PHONY: up down build logs migrate shell createsuperuser test lint

# ── Docker ──────────────────────────────────────────────
up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

logs-web:
	docker compose logs -f web

logs-worker:
	docker compose logs -f worker

# ── Django ──────────────────────────────────────────────
migrate:
	docker compose exec web python manage.py migrate

makemigrations:
	docker compose exec web python manage.py makemigrations

shell:
	docker compose exec web python manage.py shell_plus

createsuperuser:
	docker compose exec web python manage.py createsuperuser

collectstatic:
	docker compose exec web python manage.py collectstatic --noinput

# ── Testing ─────────────────────────────────────────────
test:
	docker compose exec web pytest -v --tb=short

test-cov:
	docker compose exec web pytest --cov=apps --cov-report=html -v

# ── Lint ────────────────────────────────────────────────
lint:
	docker compose exec web ruff check .

lint-fix:
	docker compose exec web ruff check --fix .

# ── First time setup ───────────────────────────────────
setup:
	cp -n .env.example .env || true
	docker compose up -d --build
	docker compose exec web python manage.py migrate
	@echo ""
	@echo "=== Setup complete! ==="
	@echo "Create admin: make createsuperuser"
	@echo "Dashboard:    http://localhost:8000"
	@echo "Admin:        http://localhost:8000/admin"
	@echo "MinIO:        http://localhost:9001"
