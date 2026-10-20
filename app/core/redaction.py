"""Masquage des données sensibles, partagé par le journal d'audit et les logs.

Une clé sensible n'est JAMAIS écrite, quelle que soit la profondeur où elle apparaît. La comparaison
ignore la casse. Ajouter ici toute nouvelle clé sensible du projet (ex. `iban`, `card_number`).
"""

from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password", "password_hash", "current_password", "new_password",
        "token", "access_token", "refresh_token", "refresh_token_hash", "previous_refresh_token_hash",
        "secret", "signature", "authorization", "confirmation_code", "api_key",
        "cookie", "set-cookie", "x-api-key", "smtp_password", "secret_jwt",
    }
)  # fmt: skip
REDACTED = "[masqué]"
MAX_STRING_LENGTH = 500


def is_sensitive(key: object) -> bool:
    return str(key).lower() in SENSITIVE_KEYS


def redact(value: Any, *, max_length: int | None = MAX_STRING_LENGTH) -> Any:
    """Copie de `value` (dict/list imbriqués) où les clés sensibles sont masquées et les chaînes tronquées."""
    if isinstance(value, dict):
        return {
            str(k): REDACTED if is_sensitive(k) else redact(v, max_length=max_length)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v, max_length=max_length) for v in value]
    if max_length is not None and isinstance(value, str) and len(value) > max_length:
        return value[:max_length] + "…"
    return value
