"""Exposition de /docs, /redoc et /openapi.json selon l'environnement."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.docs import register_docs


def build_client(environment: str) -> TestClient:
    settings = Settings(
        _env_file=None,
        ENVIRONMENT=environment,
        DATABASE_URL="postgresql://app:pw@db.internal:5432/app",
        SECRET_JWT="x7Kq9Zp2Lm4Vb8Nc1Rt6Yw3Hs5Df0GjA",  # gitleaks:allow (valeur factice de test)
        EMAIL_BACKEND="disabled",
        CORS_ORIGINS="https://admin.example.com",
        ALLOW_REMOTE_DB_IN_LOCAL=True,  # URL fictive : on ne teste ici que l'exposition de /docs
        DOCS_USERNAME="team",
        DOCS_PASSWORD="s3cret",
    )
    app = FastAPI(title="T", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    register_docs(app, settings)
    return TestClient(app)


def basic(username: str, password: str) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.parametrize("environment", ["local", "ci"])
def test_docs_are_open_in_development(environment):
    client = build_client(environment)
    assert client.get("/docs").status_code == 200
    redoc = client.get("/redoc")
    assert redoc.status_code == 200 and "redoc" in redoc.text.lower()
    assert "/ping" in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_do_not_exist_in_production(path):
    assert build_client("production").get(path).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_staging_docs_require_credentials(path):
    client = build_client("staging")
    anonymous = client.get(path)
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Basic"
    assert client.get(path, headers=basic("team", "wrong")).status_code == 401
    assert client.get(path, headers=basic("intruder", "s3cret")).status_code == 401
    assert client.get(path, headers=basic("team", "s3cret")).status_code == 200
