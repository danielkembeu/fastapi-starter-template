"""Envoi d'e-mails, selon `EMAIL_BACKEND` : console, smtp ou disabled.

- `console`  : journalise le message (développement, tests) — n'envoie rien, refusé en staging/production.
- `smtp`     : envoi réel via `smtplib` (bibliothèque standard, aucune dépendance).
- `disabled` : le projet n'envoie aucun e-mail ; tout envoi est une erreur de programmation.

Appeler `send_email` depuis un service, **après** le `commit` de l'opération (un e-mail ne s'annule pas) ;
une panne d'envoi ne doit pas annuler une opération déjà réussie : l'appelant décide s'il journalise ou relance.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import EmailBackend, settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """L'e-mail n'a pas pu être envoyé."""


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str | None = None


def _build(message: Email) -> EmailMessage:
    # Un retour à la ligne dans un en-tête permettrait d'injecter d'autres en-têtes (Bcc…).
    for value in (message.to, message.subject):
        if "\n" in value or "\r" in value:
            raise EmailError("en-tête d'e-mail invalide (retour à la ligne)")

    built = EmailMessage()
    built["From"] = settings.EMAIL_FROM
    built["To"] = message.to
    built["Subject"] = message.subject
    built.set_content(message.text)
    if message.html:
        built.add_alternative(message.html, subtype="html")
    return built


def _send_smtp(built: EmailMessage) -> None:
    timeout = settings.SMTP_TIMEOUT_SECONDS
    try:
        if settings.SMTP_USE_SSL:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            client = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
        with client:
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                client.starttls(context=ssl.create_default_context())
            if settings.SMTP_USERNAME:
                client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            client.send_message(built)
    except (smtplib.SMTPException, OSError) as exc:
        # Le type d'erreur suffit : le message d'un serveur SMTP peut contenir des identifiants.
        logger.error("Échec d'envoi d'e-mail (%s)", type(exc).__name__)
        raise EmailError("envoi impossible") from exc


def send_email(message: Email) -> None:
    backend = settings.EMAIL_BACKEND
    if backend is EmailBackend.DISABLED:
        raise EmailError("EMAIL_BACKEND=disabled : ce projet n'envoie pas d'e-mails")

    built = _build(message)
    if backend is EmailBackend.CONSOLE:
        logger.info("E-mail (console) à %s — %s\n%s", message.to, message.subject, message.text)
        return
    _send_smtp(built)
