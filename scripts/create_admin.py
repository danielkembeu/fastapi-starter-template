"""Crée le premier compte administrateur (aucune route de l'API ne peut le faire).

    python -m scripts.create_admin --email admin@example.com --first-name Ada --last-name Admin
    python -m scripts.create_admin --email admin@example.com --first-name Ada --last-name Admin --confirm

Sans `--confirm`, le script affiche la base visée et s'arrête (aperçu) : on vérifie la CIBLE avant
d'écrire. Le mot de passe est saisi de façon masquée (ou lu dans `ADMIN_PASSWORD`, pour la CI).
"""

import argparse
import getpass
import os
import sys
from urllib.parse import urlparse

from sqlmodel import Session

from app.core import database
from app.core.config import settings
from app.modules.users.service import UserService


def target_description() -> str:
    parsed = urlparse(settings.DATABASE_URL)
    return f"{settings.ENVIRONMENT.value} — {parsed.hostname or 'sqlite'}:{parsed.port or '-'}{parsed.path}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--confirm", action="store_true", help="écrire réellement en base")
    args = parser.parse_args(argv)

    if not settings.uses_postgres:
        print("Ce script concerne DATABASE_BACKEND=postgres.", file=sys.stderr)
        return 2

    print(f"Base visée : {target_description()}")
    if not args.confirm:
        print(
            f"Aperçu : créerait l'administrateur {args.email}. Relancer avec --confirm pour écrire."
        )
        return 0

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Mot de passe : ")
    with Session(database.engine) as session:
        admin = UserService.create_admin(
            session,
            email=args.email,
            password=password,
            first_name=args.first_name,
            last_name=args.last_name,
        )
    print(f"Administrateur créé : {admin.email} ({admin.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
