"""Types validés réutilisables dans les schémas d'entrée."""

import re
from typing import Annotated

from pydantic import AfterValidator, EmailStr, StringConstraints

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # limite de bcrypt : au-delà, il tronque (4.x) ou lève une erreur (5.x)


def _check_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères")
    if len(value.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Le mot de passe ne doit pas dépasser {MAX_PASSWORD_BYTES} octets")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Le mot de passe doit contenir au moins une lettre et un chiffre")
    return value


check_password = _check_password
"""Même règle, utilisable hors d'un schéma Pydantic (lève `ValueError`)."""


def _normalize_email(value: str) -> str:
    return value.strip().lower()


Password = Annotated[str, AfterValidator(_check_password)]
"""Mot de passe à l'inscription ou à la création de compte (pas à la connexion)."""

NormalizedEmail = Annotated[EmailStr, AfterValidator(_normalize_email)]
"""Adresse e-mail valide, en minuscules : l'unicité ne dépend pas de la casse."""

PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
PhoneNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9 ()\-]{6,20}$")
]
