"""Point d'entrée : crée l'application, branche les middlewares et monte les routers."""

import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.access_log import AccessLogMiddleware
from app.core.config import settings
from app.core.context import RequestContextMiddleware
from app.core.docs import register_docs
from app.core.errors import register_exception_handlers
from app.core.health import mark_started
from app.core.health import router as health_route
from app.core.logging import configure_logging
from app.core.ratelimit import register_rate_limit
from app.modules.audit.router import router as audit_route
from app.modules.auth.router import router as auth_route
from app.modules.projects.router import router as projects_route

configure_logging(settings)
logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT.value,
        # Pas d'IP ni d'en-têtes utilisateur envoyés à un tiers.
        send_default_pii=False,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Le schéma est géré exclusivement par Alembic : l'app ne crée jamais de tables elle-même.
    logger.info(
        "Application démarrée",
        extra={
            "event": "app.started",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "api_version": settings.API_VERSION,
            "database": settings.DATABASE_BACKEND.value,
            "log_level": settings.log_level_name,
            "log_format": "json" if settings.log_json else "text",
            "stacktraces_in_logs": settings.log_stacktraces,
            "error_debug": settings.expose_error_debug,
        },
    )
    mark_started()
    yield
    logger.info("Application arrêtée", extra={"event": "app.stopped"})


server = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,  # servi par register_docs, selon l'environnement
    swagger_ui_parameters={
        "filter": True,
        "displayRequestDuration": True,
        "defaultModelsExpandDepth": -1,
        "persistAuthorization": True,
        "tryItOutEnabled": True,
        "docExpansion": "list",
    },
)

register_exception_handlers(server)
register_rate_limit(server)

server.mount("/static", StaticFiles(directory="static"), name="static")


@server.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.png")


register_docs(server, settings)

server.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lisibles par un client web : identifiant de requête (support) et délai après un 429.
    expose_headers=["X-Request-ID", "Retry-After"],
)
# Ajouté en dernier = le plus extérieur : toute réponse (même une erreur CORS) porte un X-Request-ID.
# Le journal d'accès est INTÉRIEUR au contexte (il lit le request_id) mais extérieur au CORS.
server.add_middleware(AccessLogMiddleware)
server.add_middleware(RequestContextMiddleware)

server.include_router(router=health_route)

if settings.uses_postgres:
    server.include_router(router=auth_route, prefix=settings.api_prefix)
    server.include_router(router=projects_route, prefix=settings.api_prefix)
    server.include_router(router=audit_route, prefix=settings.api_prefix)
else:
    # Les modules fournis (auth, projects, audit) reposent sur SQLModel/Alembic.
    # Avec MongoDB, monter ici les routers de vos propres modules (docs/BASES_DE_DONNEES.md).
    logger.warning("DATABASE_BACKEND=%s : modules SQL non montés", settings.DATABASE_BACKEND.value)
