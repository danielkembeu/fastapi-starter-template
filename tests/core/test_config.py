"""Verrous de démarrage : une configuration dangereuse doit empêcher l'application de démarrer."""

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings

STRONG_SECRET = "x7Kq9Zp2Lm4Vb8Nc1Rt6Yw3Hs5Df0GjA"  # gitleaks:allow (valeur factice de test)

VALID_PRODUCTION = {
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql://app:pw@db.internal:5432/app",
    "SECRET_JWT": STRONG_SECRET,
    "CORS_ORIGINS": "https://admin.example.com",
    "EMAIL_BACKEND": "disabled",  # un projet qui n'envoie pas d'e-mails ; les cas smtp sont testés plus bas
}


def build(**overrides) -> Settings:
    return Settings(_env_file=None, **{**VALID_PRODUCTION, **overrides})


def test_valid_production_settings_start():
    settings = build()
    assert settings.is_production
    assert settings.cors_origins_list == ["https://admin.example.com"]


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "sqlite:///./dev.db",
        "postgresql://u:p@localhost:5432/dev",
        "postgresql://u:p@127.0.0.1:55432/dev",
    ],
)
def test_local_accepts_local_databases(url):
    assert (
        Settings(_env_file=None, ENVIRONMENT="local", DATABASE_URL=url, SECRET_JWT="x").ENVIRONMENT
        is Environment.LOCAL
    )


def test_local_refuses_a_remote_database_by_default():
    """Verrou né d'un incident : une app locale pointée sur la base de production."""
    url = "postgresql://u:p@db.remote-host.example/app_db"
    with pytest.raises(ValidationError, match="base distante"):
        Settings(_env_file=None, ENVIRONMENT="local", DATABASE_URL=url, SECRET_JWT="x")


def test_local_can_explicitly_opt_in_to_a_remote_database():
    url = "postgresql://u:p@db.remote-host.example/app_db"
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        DATABASE_URL=url,
        SECRET_JWT="x",
        ALLOW_REMOTE_DB_IN_LOCAL=True,
    )
    assert url == settings.DATABASE_URL


def test_ci_environment_is_not_subject_to_the_local_lock():
    url = "postgresql://postgres:postgres@postgres:5432/test"  # service Docker de la CI
    assert (
        Settings(_env_file=None, ENVIRONMENT="ci", DATABASE_URL=url, SECRET_JWT="x").ENVIRONMENT
        is Environment.CI
    )


def test_local_accepts_development_values():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="local",
        DATABASE_URL="sqlite://",
        SECRET_JWT="short",
    )
    assert settings.ENVIRONMENT is Environment.LOCAL
    assert not settings.is_exposed
    assert "http://localhost:3000" in settings.cors_origins_list


@pytest.mark.parametrize("secret", ["short", "changeme", "test-secret-do-not-use-in-prod"])
def test_production_rejects_weak_jwt_secret(secret):
    with pytest.raises(ValidationError, match="SECRET_JWT"):
        build(SECRET_JWT=secret)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "postgresql://u:p@localhost:5432/db",
        "postgresql://u:p@127.0.0.1:5432/db",
    ],
)
def test_production_rejects_local_database(url):
    with pytest.raises(ValidationError, match="base locale"):
        build(DATABASE_URL=url)


@pytest.mark.parametrize("origins", ["*", "", "https://a.example.com,*"])
def test_production_rejects_open_or_empty_cors(origins):
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        build(CORS_ORIGINS=origins)


def test_production_rejects_localhost_origin():
    with pytest.raises(ValidationError, match="origine locale"):
        build(CORS_ORIGINS="https://admin.example.com,http://localhost:3000")


def test_staging_requires_docs_credentials():
    staging = {"ENVIRONMENT": "staging"}
    with pytest.raises(ValidationError, match="DOCS_USERNAME"):
        build(**staging)
    assert build(**staging, DOCS_USERNAME="team", DOCS_PASSWORD="pw").is_exposed


def test_all_problems_are_reported_together():
    with pytest.raises(ValidationError) as exc:
        build(SECRET_JWT="short", DATABASE_URL="sqlite://", CORS_ORIGINS="*")
    message = str(exc.value)
    assert "SECRET_JWT" in message and "base locale" in message and "CORS_ORIGINS" in message


def test_real_environment_variable_wins_over_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.local"
    env_file.write_text("DATABASE_URL=sqlite://from-file\nSECRET_JWT=from-file\n")
    monkeypatch.delenv("DATABASE_URL")  # absente de l'environnement : le fichier s'applique
    monkeypatch.setenv("SECRET_JWT", "from-environment")  # présente : elle prime sur le fichier
    settings = Settings(_env_file=str(env_file))
    assert settings.DATABASE_URL == "sqlite://from-file"
    assert settings.SECRET_JWT == "from-environment"


# ---- Sélection de la base de données ---------------------------------------------------


def test_mongodb_requires_its_url_and_database_name():
    with pytest.raises(ValidationError, match="MONGODB_URL"):
        build(DATABASE_BACKEND="mongodb", DATABASE_URL="")
    ok = build(
        DATABASE_BACKEND="mongodb",
        DATABASE_URL="",
        MONGODB_URL="mongodb://db.internal:27017",
        MONGODB_DB_NAME="app",
    )
    assert ok.uses_mongodb and not ok.uses_postgres
    assert ok.sql_url == "sqlite://"  # moteur SQL inerte : aucune base PostgreSQL n'est jointe


def test_postgres_requires_its_url():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        build(DATABASE_URL="")


def test_a_local_mongodb_is_refused_when_exposed():
    with pytest.raises(ValidationError, match="base locale"):
        build(
            DATABASE_BACKEND="mongodb",
            MONGODB_URL="mongodb://127.0.0.1:27017",
            MONGODB_DB_NAME="app",
        )


def test_local_refuses_a_remote_mongodb_like_a_remote_postgres():
    with pytest.raises(ValidationError, match="base distante"):
        Settings(
            _env_file=None,
            ENVIRONMENT="local",
            SECRET_JWT="dev",
            DATABASE_BACKEND="mongodb",
            MONGODB_URL="mongodb://cluster.mongodb.net:27017",
            MONGODB_DB_NAME="app",
        )


# ---- E-mail ----------------------------------------------------------------------------


def test_smtp_requires_host_and_sender():
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        build(EMAIL_BACKEND="smtp")
    ok = build(
        EMAIL_BACKEND="smtp", SMTP_HOST="smtp.example.com", EMAIL_FROM="no-reply@example.com"
    )
    assert ok.EMAIL_BACKEND.value == "smtp"


def test_starttls_and_implicit_ssl_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="exclusifs"):
        build(
            EMAIL_BACKEND="smtp",
            SMTP_HOST="h",
            EMAIL_FROM="a@example.com",
            SMTP_USE_TLS=True,
            SMTP_USE_SSL=True,
        )


def test_the_console_mailer_is_refused_when_exposed_but_fine_locally():
    with pytest.raises(ValidationError, match="EMAIL_BACKEND=console"):
        build(EMAIL_BACKEND="console")
    local = Settings(_env_file=None, ENVIRONMENT="ci", SECRET_JWT="dev", DATABASE_URL="sqlite://")
    assert local.EMAIL_BACKEND.value == "console"


# ---- Stockage --------------------------------------------------------------------------


def test_cloudinary_and_s3_require_their_credentials():
    with pytest.raises(ValidationError, match="CLOUDINARY_API_KEY"):
        build(STORAGE_BACKEND="cloudinary", CLOUDINARY_CLOUD_NAME="demo")
    with pytest.raises(ValidationError, match="S3_BUCKET"):
        build(STORAGE_BACKEND="s3", S3_ACCESS_KEY_ID="id")
    build(
        STORAGE_BACKEND="cloudinary",
        CLOUDINARY_CLOUD_NAME="demo",
        CLOUDINARY_API_KEY="k",
        CLOUDINARY_API_SECRET="s",
    )
    build(STORAGE_BACKEND="s3", S3_BUCKET="b", S3_ACCESS_KEY_ID="id", S3_SECRET_ACCESS_KEY="sec")


def test_local_disk_storage_is_refused_when_exposed():
    """Le disque d'un conteneur est perdu à chaque déploiement : les fichiers disparaîtraient."""
    with pytest.raises(ValidationError, match="STORAGE_BACKEND=local"):
        build(STORAGE_BACKEND="local")


def test_backend_problems_are_checked_in_every_environment():
    """Un SMTP incomplet est une erreur même en local : on la découvre avant le déploiement."""
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        Settings(
            _env_file=None,
            ENVIRONMENT="local",
            SECRET_JWT="dev",
            DATABASE_URL="sqlite://",
            EMAIL_BACKEND="smtp",
        )


def test_upload_allowed_types_are_parsed():
    settings = build(UPLOAD_ALLOWED_TYPES="image/png, application/pdf ,")
    assert settings.upload_allowed_types == {"image/png", "application/pdf"}


# ---- Version de l'API ------------------------------------------------------------------


@pytest.mark.parametrize("version", ["v1", "v2", "v10"])
def test_valid_api_versions_build_the_prefix(version):
    assert build(API_VERSION=version).api_prefix == f"/api/{version}"


@pytest.mark.parametrize("version", ["", "1", "V1", "v0", "v1/", "../admin", "latest", "v1.2"])
def test_invalid_api_versions_are_refused(version):
    with pytest.raises(ValidationError, match="API_VERSION"):
        build(API_VERSION=version)
