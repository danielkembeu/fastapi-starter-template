"""Configuration centralisée de l'application.

Le comportement dépend de `ENVIRONMENT` (local, ci, staging, production).
Ordre de priorité : variables d'environnement réelles > fichier `.env.<ENVIRONMENT>`
> valeurs par défaut de la classe. En staging et en production, les verrous de
démarrage refusent une configuration dangereuse plutôt que de servir avec.

Chaque service tiers (base, e-mail, stockage, Redis, Sentry) se choisit par une variable
`*_BACKEND` / `*_URL` ; ses paramètres ne sont exigés que lorsqu'il est sélectionné.
Toute nouvelle variable doit être : typée ici, commentée dans `.env.example`, et — si son oubli
est dangereux — vérifiée dans `_startup_locks` avec un test dans `tests/core/test_config.py`.
"""

import os
import re
from enum import StrEnum
from functools import cached_property
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"  # poste du développeur
    CI = "ci"  # exécution des tests
    STAGING = "staging"  # pré-production
    PRODUCTION = "production"


class DatabaseBackend(StrEnum):
    POSTGRES = "postgres"  # SQLModel + Alembic (backend de référence du template)
    MONGODB = "mongodb"  # PyMongo ; voir docs/BASES_DE_DONNEES.md


class LogFormat(StrEnum):
    AUTO = "auto"  # texte lisible en local/ci, JSON en staging/production
    TEXT = "text"
    JSON = "json"


LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class EmailBackend(StrEnum):
    CONSOLE = "console"  # journalise le message (développement, tests)
    SMTP = "smtp"  # envoi réel
    DISABLED = "disabled"  # le projet n'envoie aucun e-mail


class StorageBackend(StrEnum):
    DISABLED = "disabled"  # le projet ne stocke aucun fichier
    LOCAL = "local"  # disque local (développement, tests)
    CLOUDINARY = "cloudinary"
    S3 = "s3"  # tout stockage compatible S3 (AWS, MinIO, Scaleway, R2…)


# Secrets de développement connus : refusés dès que l'environnement est exposé.
KNOWN_WEAK_SECRETS = frozenset(
    {
        "secret",
        "changeme",
        "change-me",
        "test-secret-do-not-use-in-prod",
        "ci-secret-not-used-in-prod",
    }
)

MIN_SECRET_LENGTH = 32
LOCAL_CORS_ORIGINS = "http://localhost:3000"
LOCAL_DB_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "host.docker.internal"})
# Moteur SQL inerte utilisé quand le backend est MongoDB : garde les imports valides sans base SQL.
INERT_SQL_URL = "sqlite://"


def is_local_database(url: str) -> bool:
    """Vrai pour SQLite ou une base sur la machine elle-même."""
    if url.lower().startswith("sqlite"):
        return True

    return (urlparse(url).hostname or "") in LOCAL_DB_HOSTS


def _env_file_for_current_environment() -> str:
    """Fichier `.env.<ENVIRONMENT>` : un confort de développement, jamais obligatoire."""
    env_value = os.environ.get("ENVIRONMENT", Environment.LOCAL.value)

    return f".env.{env_value}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file_for_current_environment(), extra="ignore")

    # ---- Application ------------------------------------------------------------------------
    ENVIRONMENT: Environment = Environment.LOCAL
    APP_NAME: str = "FastAPI Backend Template"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"  # noqa: S104 — dans un conteneur, écouter sur toutes les interfaces est voulu
    APP_PORT: int = 8000
    # URL publique du service (liens dans les e-mails, URLs de fichiers). Vide = non utilisée.
    APP_PUBLIC_URL: str = ""
    # Version de l'API : TOUTES les routes métier sont servies sous /api/{API_VERSION} (ex. /api/v1/projects).
    # Changer ici (v2, v3…) suffit : voir docs/VERSIONNAGE_API.md. Les sondes /health ne sont pas versionnées.
    API_VERSION: str = "v1"
    # Interrupteur de fonctionnalité : inscription ouverte à tous (false = comptes créés autrement).
    REGISTRATION_ENABLED: bool = True

    # ---- Logs et erreurs ---------------------------------------------------------------------
    # Niveau minimal des logs (DEBUG, INFO, WARNING, ERROR, CRITICAL). Vide = défaut de l'environnement :
    # DEBUG en local, INFO ailleurs.
    LOG_LEVEL: str = ""
    # auto = texte lisible en local/ci, JSON (une ligne par événement) en staging/production.
    LOG_FORMAT: LogFormat = LogFormat.AUTO
    # Traces d'appels (stack traces) dans les LOGS. None = oui partout sauf en production (où Sentry les
    # porte). Une trace peut contenir des données personnelles : ne l'activer en production qu'en connaissance de cause.
    LOG_STACKTRACES: bool | None = None
    # Détail technique (type d'exception, trace) dans la RÉPONSE d'erreur au client. None = oui en
    # local/ci, jamais en staging/production. `true` est REFUSÉ en production.
    ERROR_DEBUG: bool | None = None

    # ---- Base de données ---------------------------------------------------------------------
    DATABASE_BACKEND: DatabaseBackend = DatabaseBackend.POSTGRES
    # Garde-fou : un poste de développement ne doit pas se connecter à une base distante (c'est
    # ainsi qu'une base de production peut être modifiée par accident depuis un poste local).
    ALLOW_REMOTE_DB_IN_LOCAL: bool = False
    # PostgreSQL (obligatoire si DATABASE_BACKEND=postgres)
    DATABASE_URL: str = ""
    # Pool de connexions PostgreSQL, par worker. Règle : workers x (pool + overflow)
    # doit rester sous le `max_connections` de Postgres.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    # MongoDB (obligatoire si DATABASE_BACKEND=mongodb)
    MONGODB_URL: str = ""
    MONGODB_DB_NAME: str = ""
    MONGODB_TIMEOUT_MS: int = 2000

    # ---- Authentification --------------------------------------------------------------------
    SECRET_JWT: str
    JWT_ALGORITHM: str = "HS256"
    # Durées des jetons. L'access token est court : il n'est pas révocable avant expiration.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Protection contre le brute-force et les sessions sans limite.
    MAX_LOGIN_ATTEMPTS: int = 5  # échecs consécutifs avant verrouillage du compte
    LOGIN_LOCK_MINUTES: int = 15
    MAX_SESSIONS_PER_USER: int = 2  # au-delà, la plus ancienne session est supprimée
    # Coût de hachage bcrypt. 12 en production ; abaissé dans les tests pour qu'ils restent rapides.
    BCRYPT_ROUNDS: int = 12

    # ---- Réseau ------------------------------------------------------------------------------
    # Origines autorisées par CORS, séparées par des virgules. Jamais "*".
    CORS_ORIGINS: str = LOCAL_CORS_ORIGINS

    # ---- Redis et limitation de débit ---------------------------------------------------------
    # Cache / files (optionnel). Vide = Redis non utilisé pour autre chose que la limitation de débit.
    REDIS_URL: str = ""
    # Le compteur doit être PARTAGÉ entre les workers : en production avec plusieurs workers,
    # utiliser Redis (redis://redis:6379/0) ; `memory://` compte par processus.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    RATE_LIMIT_DEFAULT: str = "120/minute"  # par utilisateur (ou par IP si anonyme)
    RATE_LIMIT_AUTH: str = "5/minute"  # login, par IP
    RATE_LIMIT_REGISTER: str = "20/hour"  # inscription, par IP
    RATE_LIMIT_SENSITIVE: str = "10/minute"  # actions à enjeu, par utilisateur

    # ---- E-mail ------------------------------------------------------------------------------
    EMAIL_BACKEND: EmailBackend = EmailBackend.CONSOLE
    EMAIL_FROM: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True  # STARTTLS (port 587)
    SMTP_USE_SSL: bool = False  # TLS implicite (port 465) ; exclusif avec SMTP_USE_TLS
    SMTP_TIMEOUT_SECONDS: int = 10

    # ---- Stockage de fichiers ----------------------------------------------------------------
    STORAGE_BACKEND: StorageBackend = StorageBackend.DISABLED
    UPLOAD_MAX_BYTES: int = 5 * 1024 * 1024
    UPLOAD_ALLOWED_TYPES: str = "image/jpeg,image/png,image/webp"
    STORAGE_LOCAL_PATH: str = "static/uploads"
    STORAGE_LOCAL_PUBLIC_URL: str = "http://localhost:8000/static/uploads"
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    S3_BUCKET: str = ""
    S3_REGION: str = ""
    S3_ENDPOINT_URL: str = ""  # vide = AWS ; renseigné pour MinIO, Scaleway, R2…
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PUBLIC_BASE_URL: str = ""  # préfixe public des URLs de fichiers (CDN ou bucket public)

    # ---- Supervision -------------------------------------------------------------------------
    # Vide = Sentry désactivé (local, tests).
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    # Les sondes /health/* ne répondent qu'« ok » ou « down » au public. Avec cet en-tête
    # (X-Health-Token), elles détaillent chaque vérification. Vide = détail réservé au local.
    HEALTH_DETAIL_TOKEN: str = ""
    # Accès à /docs en staging (HTTP Basic). Inutilisé en local (ouvert) et en production (fermé).
    DOCS_USERNAME: str = ""
    DOCS_PASSWORD: str = ""

    @field_validator("LOG_STACKTRACES", "ERROR_DEBUG", mode="before")
    @classmethod
    def _empty_means_default(cls, value: object) -> object:
        """`LOG_STACKTRACES=` (vide, comme dans .env.example) signifie « défaut de l'environnement »."""
        return None if isinstance(value, str) and not value.strip() else value

    # ---- Dérivés -----------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def is_exposed(self) -> bool:
        """Vrai pour tout environnement joignable depuis Internet."""
        return self.ENVIRONMENT in (Environment.STAGING, Environment.PRODUCTION)

    @property
    def log_level_name(self) -> str:
        return self.LOG_LEVEL.upper() or (
            "DEBUG" if self.ENVIRONMENT is Environment.LOCAL else "INFO"
        )

    @property
    def log_json(self) -> bool:
        return self.LOG_FORMAT is LogFormat.JSON or (
            self.LOG_FORMAT is LogFormat.AUTO and self.is_exposed
        )

    @property
    def log_stacktraces(self) -> bool:
        return self.LOG_STACKTRACES if self.LOG_STACKTRACES is not None else not self.is_production

    @property
    def expose_error_debug(self) -> bool:
        if self.ERROR_DEBUG is not None:
            return self.ERROR_DEBUG
        return self.ENVIRONMENT in (Environment.LOCAL, Environment.CI)

    @property
    def uses_postgres(self) -> bool:
        return self.DATABASE_BACKEND is DatabaseBackend.POSTGRES

    @property
    def uses_mongodb(self) -> bool:
        return self.DATABASE_BACKEND is DatabaseBackend.MONGODB

    @property
    def api_prefix(self) -> str:
        """Préfixe commun de toutes les routes métier : `/api/v1`."""
        return f"/api/{self.API_VERSION}"

    @property
    def sql_url(self) -> str:
        """URL du moteur SQL : la base PostgreSQL, ou un moteur inerte si le backend est MongoDB."""
        return self.DATABASE_URL if self.uses_postgres else INERT_SQL_URL

    @cached_property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @cached_property
    def upload_allowed_types(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.UPLOAD_ALLOWED_TYPES.split(",") if t.strip())

    # ---- Verrous de démarrage ----------------------------------------------------------------
    def _backend_problems(self) -> list[str]:
        """Paramètres manquants ou incohérents, pour le backend choisi, dans TOUS les environnements."""
        problems: list[str] = []

        if self.LOG_LEVEL and self.LOG_LEVEL.upper() not in LOG_LEVELS:
            problems.append(f"LOG_LEVEL doit valoir l'une de {sorted(LOG_LEVELS)} (ou rester vide)")
        if not re.fullmatch(r"v[1-9][0-9]*", self.API_VERSION):
            problems.append("API_VERSION doit avoir la forme v1, v2, v3…")
        if self.uses_postgres and not self.DATABASE_URL:
            problems.append("DATABASE_URL est requise avec DATABASE_BACKEND=postgres")
        if self.uses_mongodb and not (self.MONGODB_URL and self.MONGODB_DB_NAME):
            problems.append(
                "MONGODB_URL et MONGODB_DB_NAME sont requises avec DATABASE_BACKEND=mongodb"
            )

        if self.EMAIL_BACKEND is EmailBackend.SMTP:
            if not (self.SMTP_HOST and self.EMAIL_FROM):
                problems.append("SMTP_HOST et EMAIL_FROM sont requis avec EMAIL_BACKEND=smtp")
            if self.SMTP_USE_TLS and self.SMTP_USE_SSL:
                problems.append("SMTP_USE_TLS et SMTP_USE_SSL sont exclusifs")

        if self.STORAGE_BACKEND is StorageBackend.CLOUDINARY and not all(
            [self.CLOUDINARY_CLOUD_NAME, self.CLOUDINARY_API_KEY, self.CLOUDINARY_API_SECRET]
        ):
            problems.append(
                "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY et CLOUDINARY_API_SECRET sont requis "
                "avec STORAGE_BACKEND=cloudinary"
            )
        if self.STORAGE_BACKEND is StorageBackend.S3 and not all(
            [self.S3_BUCKET, self.S3_ACCESS_KEY_ID, self.S3_SECRET_ACCESS_KEY]
        ):
            problems.append(
                "S3_BUCKET, S3_ACCESS_KEY_ID et S3_SECRET_ACCESS_KEY sont requis avec STORAGE_BACKEND=s3"
            )
        return problems

    def _exposure_problems(self) -> list[str]:
        """Réglages dangereux ou inutilisables dès que l'environnement est joignable depuis Internet."""
        problems: list[str] = []

        if len(self.SECRET_JWT) < MIN_SECRET_LENGTH or self.SECRET_JWT in KNOWN_WEAK_SECRETS:
            problems.append(
                f"SECRET_JWT doit faire au moins {MIN_SECRET_LENGTH} caractères "
                "et ne pas être un secret de développement connu"
            )

        database_url = (self.DATABASE_URL if self.uses_postgres else self.MONGODB_URL).lower()
        if database_url.startswith("sqlite") or is_local_database(database_url):
            problems.append("l'URL de la base de données pointe vers une base locale")

        origins = self.cors_origins_list
        if not origins or "*" in origins:
            problems.append("CORS_ORIGINS doit lister des origines explicites (jamais '*')")
        elif self.is_production and any("localhost" in o or "127.0.0.1" in o for o in origins):
            problems.append("CORS_ORIGINS contient une origine locale en production")

        if self.is_production and self.ERROR_DEBUG:
            problems.append(
                "ERROR_DEBUG=true est interdit en production : le détail technique des erreurs ne doit jamais atteindre le client"
            )

        if self.ENVIRONMENT is Environment.STAGING and not (
            self.DOCS_USERNAME and self.DOCS_PASSWORD
        ):
            problems.append("DOCS_USERNAME et DOCS_PASSWORD sont requis en staging")

        if self.EMAIL_BACKEND is EmailBackend.CONSOLE:
            problems.append(
                "EMAIL_BACKEND=console n'envoie rien : choisir smtp (ou disabled si le projet n'envoie aucun e-mail)"
            )
        if self.STORAGE_BACKEND is StorageBackend.LOCAL:
            problems.append(
                "STORAGE_BACKEND=local écrit dans le disque du conteneur, perdu à chaque déploiement : "
                "choisir cloudinary ou s3 (ou disabled)"
            )
        return problems

    @model_validator(mode="after")
    def _startup_locks(self) -> "Settings":
        """Refuse de démarrer avec une configuration dangereuse ou incomplète."""
        problems = self._backend_problems()

        if self.ENVIRONMENT is Environment.LOCAL:
            remote_url = self.DATABASE_URL if self.uses_postgres else self.MONGODB_URL
            if (
                remote_url
                and not self.ALLOW_REMOTE_DB_IN_LOCAL
                and not is_local_database(remote_url)
            ):
                problems.append(
                    "l'URL de la base de données pointe vers une base distante "
                    f"({urlparse(remote_url).hostname}) : utilisez une base locale (make db-up) ; "
                    "si c'est volontaire, définissez ALLOW_REMOTE_DB_IN_LOCAL=true"
                )
        elif self.is_exposed:
            problems += self._exposure_problems()

        if problems:
            raise ValueError(
                f"Configuration refusée en {self.ENVIRONMENT.value} : " + " ; ".join(problems)
            )
        return self


# Valeurs lues depuis l'environnement : mypy ne les voit pas comme arguments.
settings = Settings()  # type: ignore[call-arg]
