# Point d'entrée unique des commandes du projet.
# Les mêmes cibles sont utilisées en local, dans les hooks git et dans la CI :
# ce qui passe chez toi passe en CI.

.DEFAULT_GOAL := help
.PHONY: help install install-extras hooks hooks-all dev lint fix type test test-pg cov check docs \
	migrate rev downgrade heads drift audit up down db-reset db-shell create-admin

PY := python

# Seuil de couverture minimal. À relever à mesure que la suite grandit, jamais à abaisser pour « faire passer ».
COV_MIN ?= 90

help:  ## Affiche cette aide
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- installation

install:  ## Installe les dépendances applicatives et de développement
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

install-extras:  ## Installe les dépendances optionnelles : make install-extras EXTRAS="storage mongo"
	@test -n "$(EXTRAS)" || (echo "Usage : make install-extras EXTRAS=\"storage mongo\"" && exit 1)
	@for extra in $(EXTRAS); do $(PY) -m pip install -r requirements-$$extra.txt; done

hooks:  ## Installe les hooks git (commit rapide + push complet)
	pre-commit install
	pre-commit install --hook-type pre-push
	@echo "Hooks installés : commit -> lint, push -> types + tests"

hooks-all:  ## Exécute tous les hooks sur tous les fichiers (commit, puis push)
	pre-commit run --all-files
	pre-commit run --all-files --hook-stage pre-push

# ------------------------------------------------------------------ exécution

dev:  ## Démarre le serveur de développement avec rechargement (APP_HOST / APP_PORT)
	fastapi dev app/server.py --reload --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000}
# 	uvicorn app.server:server --reload --host $${APP_HOST:-127.0.0.1} --port $${APP_PORT:-8000}

# --------------------------------------------------------------------- qualité

lint:  ## Vérifie le style et les erreurs (sans rien modifier)
	$(PY) -m ruff check app tests scripts
	$(PY) -m ruff format --check app tests scripts

fix:  ## Corrige automatiquement ce qui peut l'être, puis formate
	$(PY) -m ruff check --fix app tests scripts
	$(PY) -m ruff format app tests scripts

type:  ## Vérifie les types (mypy)
	$(PY) -m mypy app

test:  ## Lance la suite de tests (SQLite, rapide)
	$(PY) -m pytest

test-pg:  ## Lance toute la suite sur PostgreSQL (nécessite make up)
	TEST_DATABASE_URL=postgresql://postgres:pw@127.0.0.1:$${POSTGRES_PORT:-55432}/app_test \
		$(PY) -m pytest -p no:cacheprovider

cov:  ## Lance les tests avec le seuil de couverture
	$(PY) -m pytest --cov=app --cov-report=term-missing --cov-fail-under=$(COV_MIN)

check: lint type cov  ## Tout ce que la CI vérifie — à lancer avant de pousser

docs:  ## Régénère API_REFERENCE.md depuis le code (la CI vérifie qu'il est à jour)
	$(PY) -m scripts.generate_api_reference

# ------------------------------------------------------------------ migrations

migrate:  ## Applique les migrations en attente
	alembic upgrade head

rev:  ## Crée une migration : make rev m="ajout colonne x" (formatée automatiquement par ruff)
	@test -n "$(m)" || (echo "Usage : make rev m=\"description\"" && exit 1)
	alembic revision --autogenerate -m "$(m)"

downgrade:  ## Annule la dernière migration
	alembic downgrade -1

heads:  ## Vérifie qu'il n'y a qu'une seule tête de migration
	@test $$(alembic heads 2>/dev/null | grep -c '(head)') -le 1 \
		|| (echo "Plusieurs têtes Alembic : les branches de migration doivent être fusionnées" && exit 1)
	@echo "Une seule tête de migration."

drift:  ## Échoue si les modèles et les migrations ne sont pas synchrones (nécessite DATABASE_URL migrée)
	alembic check

# ------------------------------------------------------- services de développement
# docker compose ou podman compose, selon ce qui est installé.
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "podman compose")
# Profils optionnels : make up PROFILES="cache mail"  (cache=Redis, mongo, mail=boîte mail, storage=MinIO)
PROFILES ?=
COMPOSE_PROFILES_ARGS = $(foreach p,$(PROFILES),--profile $(p))

up:  ## Démarre PostgreSQL (+ services optionnels : PROFILES="cache mongo mail storage")
	$(COMPOSE) $(COMPOSE_PROFILES_ARGS) up -d --wait
	@echo "Services prêts. PostgreSQL : 127.0.0.1:$${POSTGRES_PORT:-55432} (bases app_dev, app_test)"

down:  ## Arrête les services (les données sont conservées)
	$(COMPOSE) --profile cache --profile mongo --profile mail --profile storage down

db-reset:  ## ⚠ Efface et recrée la base de DÉVELOPPEMENT locale (puis make migrate)
	$(COMPOSE) exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS app_dev" -c "CREATE DATABASE app_dev"

db-shell:  ## Ouvre psql sur la base de développement
	$(COMPOSE) exec postgres psql -U postgres -d app_dev

create-admin:  ## Aperçu du premier admin (CONFIRM=1 pour écrire) : make create-admin EMAIL=… FIRST=… LAST=…
	$(PY) -m scripts.create_admin --email "$(EMAIL)" --first-name "$(FIRST)" --last-name "$(LAST)" $(if $(CONFIRM),--confirm,)

# ---------------------------------------------------------------------- sécurité

audit:  ## Signale les vulnérabilités connues des dépendances
	$(PY) -m pip_audit -r requirements.txt
