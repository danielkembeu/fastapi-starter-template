"""`DATABASE_BACKEND` change réellement ce que l'application monte.

Exécuté dans un sous-processus : `app.server` lit la configuration à l'import, et la recharger dans le
processus de test polluerait l'état global (routes, moteur, limiteur) des autres tests.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNIPPET = (
    "import json; from fastapi.routing import APIRoute; from app.server import server; "
    "print(json.dumps(sorted({r.path for r in server.routes if isinstance(r, APIRoute)})))"
)


def routes_with(**env) -> list[str]:
    base = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "TEST_DATABASE_URL"}}
    base.update({"ENVIRONMENT": "ci", "SECRET_JWT": "ci-secret-not-used-in-prod", "SENTRY_DSN": ""})
    result = subprocess.run(
        [sys.executable, "-c", SNIPPET],
        cwd=ROOT,
        env={**base, "PYTHONPATH": str(ROOT), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_postgres_mounts_the_sql_modules():
    paths = routes_with(DATABASE_BACKEND="postgres", DATABASE_URL="sqlite://")
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/projects" in paths
    assert "/api/v1/admin/audit-logs" in paths


def test_mongodb_mounts_only_the_probes_until_you_add_your_own_modules():
    paths = routes_with(
        DATABASE_BACKEND="mongodb",
        MONGODB_URL="mongodb://127.0.0.1:27017",
        MONGODB_DB_NAME="app",
    )
    assert {"/health/live", "/health/ready", "/health/startup"} <= set(paths)
    assert not [p for p in paths if p.startswith("/api/")]


# ---- Version de l'API ----------------------------------------------------------------


def test_every_business_route_lives_under_the_versioned_prefix():
    """Règle globale : /api/{version}/… pour tout, sauf sondes, documentation et favicon."""
    paths = routes_with(DATABASE_BACKEND="postgres", DATABASE_URL="sqlite://")
    exempt = {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}
    business = [p for p in paths if not p.startswith("/health/") and p not in exempt]
    assert business, "aucune route métier trouvée"
    assert all(p.startswith("/api/v1/") for p in business), business


def test_changing_api_version_moves_every_route_at_once():
    """Passer à v2 = une variable : plus aucune route /api/v1, tout est sous /api/v2."""
    paths = routes_with(DATABASE_BACKEND="postgres", DATABASE_URL="sqlite://", API_VERSION="v2")
    assert "/api/v2/auth/login" in paths and "/api/v2/projects" in paths
    assert not [p for p in paths if p.startswith("/api/v1")]
    assert "/health/ready" in paths  # les sondes ne sont jamais versionnées
