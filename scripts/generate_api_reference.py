"""Génère API_REFERENCE.md depuis le schéma OpenAPI et la matrice RBAC réelle.

Le document ne peut donc pas diverger du code : chaque route, paramètre, champ, code d'erreur et
rôle autorisé est lu dans l'application. Aucune base de données n'est contactée (import seul).

    python -m scripts.generate_api_reference            # (ré)écrit API_REFERENCE.md
    python -m scripts.generate_api_reference --check    # échoue si le fichier n'est pas à jour (CI)
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Import de l'application SANS toucher aucune base ni aucun fichier .env : environnement forcé.
os.environ["ENVIRONMENT"] = "ci"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_JWT"] = "documentation-only"  # noqa: S105 — génération de doc, aucun secret
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["SENTRY_DSN"] = ""

from fastapi.routing import APIRoute

from app.core.authz import ROLE_PERMISSIONS
from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.security import get_current_user
from app.server import server

OUTPUT = Path(__file__).resolve().parents[1] / "API_REFERENCE.md"

ROLE_LABELS = {"user": "utilisateur", "admin": "admin"}

HEADER = f"""# Référence de l'API

> **Document généré automatiquement** par `python -m scripts.generate_api_reference` à partir du code
> (schéma OpenAPI + matrice des rôles). Ne pas modifier à la main : `make docs` le régénère et la CI
> vérifie qu'il est à jour.

## Conventions générales

| Sujet | Règle |
|---|---|
| Base URL | `https://<domaine>` — toutes les routes métier sont sous `{settings.api_prefix}` (version : `API_VERSION`) ; les sondes `/health` ne sont pas versionnées |
| Authentification | `Authorization: Bearer <access_token>` (obtenu par `POST {settings.api_prefix}/auth/login`) |
| Format | JSON, dates ISO 8601, identifiants UUID |
| Erreurs | toujours `{{"error": {{"code", "message", "status", "request_id", "details"}}}}` : se baser sur `code` (stable), jamais sur `message` ; `request_id` à communiquer au support (voir `docs/LOGS_ET_ERREURS.md`) |
| Validation | une entrée invalide renvoie **400** (et non 422) |
| PATCH | partiel : seuls les champs envoyés sont modifiés |
| Rôles | `utilisateur` (user), `admin` |

### Listes paginées

Tous les endpoints qui renvoient une collection sont paginés, filtrables et triables (voir `docs/PAGINATION.md`).

| Paramètre | Défaut | Règle |
|---|---|---|
| `limit` | {DEFAULT_LIMIT} | 1 à {MAX_LIMIT} |
| `offset` | 0 | ≥ 0 |
| `sort` | variable | champ de la liste blanche de l'endpoint ; préfixe `-` pour décroissant |

Réponse : `{{"items": [...], "total": N, "limit": L, "offset": O, "has_more": true|false}}`

### Codes de statut courants

| Code | Sens |
|---|---|
| 400 | entrée invalide ou règle métier non respectée |
| 401 | jeton absent, invalide ou expiré |
| 403 | rôle insuffisant, ou ressource d'un autre utilisateur |
| 404 | ressource introuvable |
| 409 | conflit d'état (doublon, déjà pris, état incompatible) |
| 429 | limite de débit atteinte — respecter l'en-tête `Retry-After` |
| 503 | service tiers ou dépendance indisponible |

"""


# ---------------------------------------------------------------------------------------
# Accès : lu dans les dépendances réelles de chaque route
# ---------------------------------------------------------------------------------------


def _walk(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _walk(sub)


def access_of(route: APIRoute) -> str:
    calls = list(_walk(route.dependant))
    authenticated = any(call is get_current_user for call in calls)
    requirements = [
        call.required_permissions for call in calls if hasattr(call, "required_permissions")
    ]
    if not authenticated and not requirements:
        return "public (aucun jeton)"

    roles = []
    for role, permissions in ROLE_PERMISSIONS.items():
        if all(any(p in permissions for p in group) for group in requirements):
            roles.append(role.value)
    label = ", ".join(ROLE_LABELS[r] for r in roles)
    if set(roles) == set(ROLE_LABELS):
        return "tout utilisateur connecté"
    return label


# ---------------------------------------------------------------------------------------
# Rendu des schémas
# ---------------------------------------------------------------------------------------


class Schemas:
    def __init__(self, spec: dict):
        self.components = spec.get("components", {}).get("schemas", {})

    def resolve(self, schema: dict) -> dict:
        ref = schema.get("$ref")
        return self.components.get(ref.rsplit("/", 1)[-1], {}) if ref else schema

    def type_of(self, schema: dict) -> str:
        if "$ref" in schema:
            return schema["$ref"].rsplit("/", 1)[-1]
        if "anyOf" in schema:
            parts = [self.type_of(s) for s in schema["anyOf"]]
            return " \\| ".join(p for p in parts if p != "null") + (
                " (nullable)" if "null" in parts else ""
            )
        if "enum" in schema:
            return " \\| ".join(f"`{v}`" for v in schema["enum"])
        kind = schema.get("type", "any")
        if kind == "array":
            return f"liste de {self.type_of(schema.get('items', {}))}"
        fmt = schema.get("format")
        return f"{kind} ({fmt})" if fmt else kind

    def constraints(self, schema: dict) -> str:
        pieces = []
        schema = schema.get("anyOf", [schema])[0] if "anyOf" in schema else schema
        for key, label in (
            ("minimum", "min"),
            ("maximum", "max"),
            ("exclusiveMinimum", ">"),
            ("exclusiveMaximum", "<"),
            ("minLength", "longueur min"),
            ("maxLength", "longueur max"),
            ("minItems", "éléments min"),
            ("maxItems", "éléments max"),
            ("pattern", "motif"),
        ):
            if key in schema:
                pieces.append(f"{label} {schema[key]}")
        return ", ".join(pieces)

    def fields(self, schema: dict) -> list[tuple[str, str, bool, str, str]]:
        schema = self.resolve(schema)
        required = set(schema.get("required", []))
        rows = []
        for name, prop in schema.get("properties", {}).items():
            default = "" if "default" not in prop else f"`{prop['default']!r}`".replace("'", '"')
            rows.append(
                (
                    name,
                    self.type_of(prop),
                    name in required,
                    default,
                    self.constraints(prop) or prop.get("description", ""),
                )
            )
        return rows


def _escape(text: str) -> str:
    return re.sub(r"(?<!\\)\|", r"\\|", text.replace("\n", " "))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_escape(str(c)) for c in row) + " |" for row in rows]
    return "\n".join(out)


def render_operation(route: APIRoute, method: str, spec: dict, schemas: Schemas) -> str:
    operation = spec["paths"][route.path][method.lower()]
    lines = [f"### `{method} {route.path}`", ""]

    summary = (route.description or "").strip()
    if summary:
        lines += [summary, ""]

    lines += [f"**Accès** : {access_of(route)}", ""]

    params = operation.get("parameters", [])
    if params:
        rows = []
        for p in params:
            sch = p.get("schema", {})
            default = f"`{sch['default']}`" if "default" in sch else ""
            extra = schemas.constraints(sch)
            description = p.get("description", "")
            rows.append(
                [
                    f"`{p['name']}`",
                    {"path": "chemin", "query": "requête", "header": "en-tête"}.get(
                        p["in"], p["in"]
                    ),
                    schemas.type_of(sch),
                    "oui" if p.get("required") else "non",
                    default,
                    "; ".join(x for x in (description, extra) if x),
                ]
            )
        lines += [
            "**Paramètres**",
            "",
            _table(["Nom", "Où", "Type", "Requis", "Défaut", "Détail"], rows),
            "",
        ]

    body = operation.get("requestBody", {}).get("content", {})
    for media, content in body.items():
        rows = [
            [f"`{n}`", t, "oui" if r else "non", d, c]
            for n, t, r, d, c in schemas.fields(content["schema"])
        ]
        label = "Corps (multipart : fichier)" if "multipart" in media else "Corps JSON"
        if rows:
            lines += [
                f"**{label}**",
                "",
                _table(["Champ", "Type", "Requis", "Défaut", "Détail"], rows),
                "",
            ]

    responses = operation.get("responses", {})
    ok = [(code, r) for code, r in responses.items() if code.startswith("2")]
    for code, response in ok:
        content = response.get("content", {}).get("application/json", {})
        if content.get("schema"):
            schema = content["schema"]
            name = schemas.type_of(schema)
            resolved = schemas.resolve(schema)
            lines += [f"**Réponse {code}** — `{name}`", ""]
            rows = [[f"`{n}`", t] for n, t, _r, _d, _c in schemas.fields(resolved)]
            if rows:
                lines += [_table(["Champ", "Type"], rows), ""]
        else:
            lines += [f"**Réponse {code}** — sans corps", ""]

    errors = sorted(c for c in responses if c.isdigit() and not c.startswith("2") and c != "422")
    if errors:
        lines += ["**Erreurs possibles** : " + ", ".join(f"`{c}`" for c in errors), ""]
    return "\n".join(lines)


def build() -> str:
    spec = server.openapi()
    schemas = Schemas(spec)
    sections: dict[str, list[str]] = {}
    counts: dict[str, int] = {}

    for route in server.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        tag = (route.tags or ["Divers"])[0]
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            sections.setdefault(tag, []).append(render_operation(route, method, spec, schemas))
            counts[tag] = counts.get(tag, 0) + 1

    toc = ["## Sommaire", ""] + [f"- **{tag}** — {n} route(s)" for tag, n in counts.items()] + [""]
    body = []
    for tag, operations in sections.items():
        body += [f"## {tag}", "", *operations]
    return HEADER + "\n".join(toc) + "\n" + "\n".join(body).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="Échoue si API_REFERENCE.md est obsolète"
    )
    args = parser.parse_args()

    content = build()
    if args.check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        if current != content:
            print("API_REFERENCE.md est obsolète : lancez `make docs` et commitez le résultat.")
            return 1
        print("API_REFERENCE.md est à jour.")
        return 0

    OUTPUT.write_text(content)
    print(
        f"{OUTPUT.name} écrit ({content.count(chr(10))} lignes, {len(server.routes)} routes enregistrées)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
