"""Configuration des logs, adaptée à l'environnement.

| Réglage            | local           | ci            | staging        | production     |
|--------------------|-----------------|---------------|----------------|----------------|
| niveau par défaut  | DEBUG           | INFO          | INFO           | INFO           |
| format             | texte lisible   | texte lisible | JSON           | JSON           |
| traces d'appels    | oui             | oui           | oui            | non (Sentry)   |

Tout est surchargeable : `LOG_LEVEL`, `LOG_FORMAT`, `LOG_STACKTRACES` (voir .env.example).

Conventions (détail dans docs/LOGS_ET_ERREURS.md) :
- niveaux : DEBUG (diagnostic fin) · INFO (fonctionnement normal, y compris les succès) · WARNING (anormal mais géré :
  refus, échec de connexion) · ERROR (une opération a échoué par NOTRE faute) · CRITICAL (le service ne peut plus fonctionner) ;
- un événement important porte `extra={"event": "domaine.action", ...}` : nom stable, filtrable (`auth.login.succeeded`) ;
- jamais de secret, de mot de passe, de jeton ni de donnée personnelle superflue : les clés sensibles sont masquées
  automatiquement, mais le premier réflexe est de ne pas les logger ;
- l'identifiant de requête (`request_id`) est ajouté à chaque ligne : il relie logs, réponse d'erreur, Sentry et audit.
"""

import copy
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.context import current_context
from app.core.redaction import redact

# Attributs standard d'un LogRecord : tout le reste vient de `extra=` et est publié comme champ.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("x", logging.INFO, "x", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and not key.startswith("_") and value is not None
    }


def _exception_text(
    record: logging.LogRecord, formatter: logging.Formatter, traces: bool
) -> str | None:
    """Trace complète si autorisée ; sinon seulement le TYPE de l'exception (le message peut contenir des données)."""
    if not record.exc_info or record.exc_info[0] is None:
        return None
    if traces:
        return formatter.formatException(record.exc_info)
    return record.exc_info[0].__name__


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par événement — pour les agrégateurs (Loki, Datadog, CloudWatch…) et `jq`."""

    def __init__(self, *, stacktraces: bool, service: str = "", environment: str = "") -> None:
        super().__init__()
        self.stacktraces = stacktraces
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self.service:
            entry["service"] = self.service
        if self.environment:
            entry["env"] = self.environment

        fields = redact(_extra_fields(record), max_length=2000)
        request_id = fields.pop("request_id", None) or current_context().request_id
        if request_id:
            entry["request_id"] = request_id
        entry.update(fields)

        exception = _exception_text(record, self, self.stacktraces)
        if exception:
            entry["exception"] = exception
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Texte lisible pour le développement : `heure NIVEAU logger: message  clé=valeur …`."""

    def __init__(self, *, stacktraces: bool) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        self.stacktraces = stacktraces

    def format(self, record: logging.LogRecord) -> str:
        # `Formatter.format` ajoute lui-même l'exception complète : on la retire de la copie pour que
        # SEULE notre politique (`stacktraces`) décide de ce qui est écrit.
        bare = copy.copy(record)
        bare.exc_info = bare.exc_text = bare.stack_info = None
        line = super().format(bare)
        fields = redact(_extra_fields(record), max_length=300)
        request_id = fields.pop("request_id", None) or current_context().request_id
        if request_id:
            fields = {"request_id": request_id, **fields}
        if fields:
            line += "  " + " ".join(f"{key}={value}" for key, value in fields.items())
        exception = _exception_text(record, self, self.stacktraces)
        return f"{line}\n{exception}" if exception else line

    def formatException(self, ei: Any) -> str:
        return super().formatException(ei)


def build_formatter(settings: Settings) -> logging.Formatter:
    if settings.log_json:
        return JsonFormatter(
            stacktraces=settings.log_stacktraces,
            service=settings.APP_NAME,
            environment=settings.ENVIRONMENT.value,
        )
    return TextFormatter(stacktraces=settings.log_stacktraces)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter(settings))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level_name)

    # Le journal d'accès est tenu par `app.core.access_log` (structuré, avec request_id) :
    # on coupe celui d'uvicorn pour ne pas avoir chaque requête en double.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").propagate = False
    # Les bibliothèques bavardes ne doivent pas noyer nos logs en DEBUG.
    for noisy in ("multipart", "httpx", "httpcore", "watchfiles", "passlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
