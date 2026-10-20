"""Envoi d'e-mails : trois backends, aucune panne SMTP ne doit fuiter d'identifiants."""

import logging
import smtplib
from typing import ClassVar

import pytest

from app.core import email as email_module
from app.core.config import EmailBackend
from app.core.email import Email, EmailError, send_email

MESSAGE = Email(
    to="ada@example.com", subject="Bienvenue", text="Bonjour Ada", html="<p>Bonjour</p>"
)


@pytest.fixture(name="configure")
def configure_fixture(monkeypatch):
    def apply(**values):
        for key, value in values.items():
            monkeypatch.setattr(f"app.core.config.settings.{key}", value)

    apply(EMAIL_FROM="no-reply@example.com")
    return apply


class FakeSMTP:
    """Remplace smtplib.SMTP / SMTP_SSL et enregistre ce qui s'y passe."""

    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[str] = []
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, message):
        self.sent = message


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeSMTP.instances.clear()


def test_console_backend_logs_instead_of_sending(configure, caplog):
    configure(EMAIL_BACKEND=EmailBackend.CONSOLE)
    with caplog.at_level(logging.INFO, logger="app.core.email"):
        send_email(MESSAGE)
    assert "ada@example.com" in caplog.text and "Bonjour Ada" in caplog.text


def test_disabled_backend_refuses_any_sending(configure):
    configure(EMAIL_BACKEND=EmailBackend.DISABLED)
    with pytest.raises(EmailError, match="disabled"):
        send_email(MESSAGE)


def test_smtp_with_starttls_authenticates_and_sends_both_formats(configure, monkeypatch):
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    configure(
        EMAIL_BACKEND=EmailBackend.SMTP,
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_USERNAME="mailer",
        SMTP_PASSWORD="pw",
        SMTP_USE_TLS=True,
        SMTP_USE_SSL=False,
    )

    send_email(MESSAGE)

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", "login:mailer"]
    assert smtp.sent["To"] == "ada@example.com" and smtp.sent["From"] == "no-reply@example.com"
    assert smtp.sent.is_multipart()  # texte + HTML


def test_smtp_over_ssl_uses_the_ssl_client_without_starttls(configure, monkeypatch):
    monkeypatch.setattr(email_module.smtplib, "SMTP_SSL", FakeSMTP)
    configure(
        EMAIL_BACKEND=EmailBackend.SMTP,
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=465,
        SMTP_USERNAME="",
        SMTP_USE_TLS=False,
        SMTP_USE_SSL=True,
    )
    send_email(MESSAGE)
    smtp = FakeSMTP.instances[0]
    assert smtp.calls == [] and smtp.sent is not None and smtp.context is not None


@pytest.mark.parametrize("field", ["to", "subject"])
def test_header_injection_is_refused(configure, field):
    """Un retour à la ligne dans un en-tête permettrait d'ajouter un destinataire caché (Bcc)."""
    configure(EMAIL_BACKEND=EmailBackend.CONSOLE)
    data = {
        "to": "a@example.com",
        "subject": "Sujet",
        "text": "x",
        field: "valeur\nBcc: v@evil.test",
    }
    with pytest.raises(EmailError):
        send_email(Email(**data))


def test_a_smtp_failure_raises_a_generic_error_and_never_logs_the_server_message(
    configure, monkeypatch, caplog
):
    class Broken(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"mot de passe hunter2 refuse")

    monkeypatch.setattr(email_module.smtplib, "SMTP", Broken)
    configure(
        EMAIL_BACKEND=EmailBackend.SMTP,
        SMTP_HOST="smtp.example.com",
        SMTP_USERNAME="mailer",
        SMTP_USE_TLS=False,
    )

    with caplog.at_level(logging.ERROR), pytest.raises(EmailError, match="impossible"):
        send_email(MESSAGE)
    assert "hunter2" not in caplog.text
    assert "SMTPAuthenticationError" in caplog.text


def test_a_network_error_is_wrapped_too(configure, monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(email_module.smtplib, "SMTP", refuse)
    configure(EMAIL_BACKEND=EmailBackend.SMTP, SMTP_HOST="127.0.0.1", SMTP_USE_TLS=False)
    with pytest.raises(EmailError):
        send_email(MESSAGE)
