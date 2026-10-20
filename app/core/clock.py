"""Horloge unique de l'application : UTC partout, jamais l'heure locale du serveur.

Les colonnes `TIMESTAMP` de la base ne portent pas de fuseau. On y stocke donc toujours de l'UTC,
sans `tzinfo` (« naïf mais UTC ») : un serveur réglé sur un autre fuseau, ou un changement d'heure,
ne décale ni expirations de jetons ni verrouillages de compte.

Règle : n'appeler JAMAIS `datetime.now()` / `datetime.utcnow()` — le lint (ruff DTZ) l'interdit.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Maintenant, en UTC, sans fuseau (format des colonnes de la base)."""
    return datetime.now(UTC).replace(tzinfo=None)
