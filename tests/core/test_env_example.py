""".env.example est la documentation des variables : il doit rester synchrone avec `Settings`."""

from pathlib import Path

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# Lues hors de `Settings` : par le Dockerfile ou par docker-compose.yml.
OUTSIDE_SETTINGS = {
    "FORWARDED_ALLOW_IPS",
    "WEB_CONCURRENCY",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "REDIS_PORT",
    "MONGO_PORT",
    "SMTP_DEV_PORT",
    "MAIL_UI_PORT",
    "MINIO_PORT",
    "MINIO_CONSOLE_PORT",
}


def documented_variables() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            names.add(stripped.split("=", 1)[0])
    return names


def test_every_setting_is_documented_in_env_example():
    missing = set(Settings.model_fields) - documented_variables()
    assert missing == set(), f"variables absentes de .env.example : {sorted(missing)}"


def test_env_example_documents_nothing_unknown():
    unknown = documented_variables() - set(Settings.model_fields) - OUTSIDE_SETTINGS
    assert unknown == set(), f"variables de .env.example inconnues de Settings : {sorted(unknown)}"


def test_env_example_loads_as_a_valid_local_configuration(monkeypatch):
    """Copier le fichier tel quel (avec un SECRET_JWT) doit donner une configuration locale valide."""
    for name in documented_variables():  # l'environnement du test l'emporterait sur le fichier
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=str(ENV_EXAMPLE), SECRET_JWT="local-dev-only-secret")
    assert settings.ENVIRONMENT.value == "local"
    assert settings.uses_postgres and settings.DATABASE_URL.startswith("postgresql://")
