# Architecture

## Organisation « par fonctionnalité »

Chaque domaine est un dossier autonome dans `app/modules/<feature>/` :

| Fichier | Rôle | Interdit |
|---|---|---|
| `router.py` | déclare la route, la **permission** (`Requires(...)`), les codes d'erreur (`err(...)`), délègue | toute logique métier |
| `service.py` | la logique métier, les transactions, l'audit | dépendre de l'objet `Request` |
| `schemas.py` | formes d'entrée/sortie (Pydantic), modèles de filtres | accéder à la base |
| `models.py`, `enums.py` | tables SQLModel et états | logique |

**Pourquoi** : on teste un service sans HTTP, on relit un router en dix secondes, et on ajoute une fonctionnalité sans toucher aux autres.

`app/core/` contient l'infrastructure transverse et **ne dépend d'aucun module métier**, à deux exceptions
assumées : `security.py` et `authz.py` lisent le modèle `User` (qui authentifie tout le reste).

```text
app/core/
 config      réglages, environnements, verrous de démarrage     authz      RBAC (le SEUL endroit où l'on autorise)
 security    JWT, hachage, utilisateur courant                  pagination limit/offset, tri en liste blanche, Page[T]
 clock       utc_now() — l'unique horloge                        ratelimit  limitation de débit (Redis, fail-open)
 context     IP / navigateur / X-Request-ID (ContextVar)         health     sondes live / startup / ready
 errors      format d'erreur unique, gestionnaires globaux       logging    logs lisibles (local) ou JSON
 docs        exposition de /docs selon l'environnement           validators types validés réutilisables
 database    couche SQL (PostgreSQL)                             mongo      couche MongoDB (optionnelle)
 email       console / smtp / disabled                           storage    local / cloudinary / s3 / disabled
 sql         idiomes SQLModel (eager)
```

## Le chemin d'une requête

```text
Client ──▶ RequestContextMiddleware   pose IP / navigateur / X-Request-ID (ContextVar)
       ──▶ RateLimitMiddleware        par utilisateur (ou IP) ; 429 + Retry-After si dépassé
       ──▶ CORSMiddleware
       ──▶ route : Requires(Permission.X)   → 401 (non authentifié) ou 403 (permission manquante)
                   validation Pydantic       → 400 (le 422 de FastAPI est remplacé)
                   service : règles, UPDATE conditionnels, audit, commit unique
       ◀── réponse (en-tête X-Request-ID toujours présent)
```

- **Une requête = une transaction.** Le service fait tous ses changements puis un seul `commit()`. Une erreur à mi-chemin ne laisse aucune trace.
- **Le contexte de requête** est un `ContextVar` : les services journalisent sans recevoir `Request`. Le middleware est le plus extérieur pour que même un 429 ait un `X-Request-ID`.
- **Format d'erreur unique** `{"error": {code, message, status, request_id, details}}` avec des codes stables (`ErrorCode`), documenté par `responses=err(401, 403, 404)` : voir `docs/LOGS_ET_ERREURS.md`.
- **500 génériques** : aucune trace renvoyée ; l'`X-Request-ID` permet de retrouver l'erreur dans les logs et Sentry.

## Montage des modules selon le backend

`app/server.py` monte `auth`, `projects` et `audit` quand `DATABASE_BACKEND=postgres`. Avec `mongodb`, seuls les
sondes de santé sont montées : vous ajoutez vos propres routers (voir `docs/BASES_DE_DONNEES.md`).

## Autorisation : `app/core/authz.py`

Trois notions distinctes :

- **Rôle** — qui es-tu ? (`User.role`)
- **Permission** — quel *type* d'action ? (`Permission.PROJECT_CREATE`), accordée par `ROLE_PERMISSIONS`
- **Portée** — sur quelles lignes ? `own` / `all`, via les permissions `*_OWN` / `*_ALL` et `ensure_owner_or_permission`

Un endpoint déclare ce qu'il **fait**, jamais « si l'utilisateur est admin » :

```python
EditorDep = Annotated[User, RequiresAny(Permission.PROJECT_UPDATE_OWN, Permission.PROJECT_UPDATE_ALL)]
```

Ajouter un rôle = une entrée dans `ROLE_PERMISSIONS` (+ la valeur dans `UserRole` et une migration), sans toucher un router.

**Limite assumée** : le RBAC dit si un rôle peut faire ce *type* d'action. Savoir si une *transition* est légale (machine
à états) reste de la logique métier, dans le service (voir `ALLOWED_TRANSITIONS` dans `projects/service.py`).

**Aucune route ne crée un rôle privilégié.** Le premier administrateur se crée par `make create-admin`
(`scripts/create_admin.py` → `UserService.create_admin`), qui affiche la base visée et fait un aperçu par défaut.

## Pagination, filtres, tri

Une liste = un modèle de filtres qui hérite de `PageQuery` + `paginate()`. Voir `docs/PAGINATION.md`.

## Erreurs et codes HTTP

`400` entrée invalide ou règle métier (`validation_error` + `details` par champ) · `401` non authentifié · `403` permission/portée · `404` introuvable
(aussi pour la ressource d'autrui, afin de ne pas révéler son existence) · `409` conflit d'état ·
`429` limite de débit · `503` service non configuré. Chaque `403` d'un utilisateur authentifié est tracé dans l'audit
(`access.denied`).

## Base de données

- **PostgreSQL** en dev/prod ; SQLite uniquement pour la suite de tests rapide (la CI lance aussi la suite sur PostgreSQL). Alternative : MongoDB (`docs/BASES_DE_DONNEES.md`).
- **Alembic est le seul maître du schéma** (`docs/MIGRATIONS.md`). La CI vérifie : base vierge → `upgrade head`, **aucune dérive** modèles ⇄ migrations, retour arrière et rejeu, **une seule tête**.
- **Dates** : toujours `utc_now()` (UTC, sans fuseau, comme les colonnes `TIMESTAMP`).
- **Suppression logique** des comptes (`status = deleted`) : l'historique reste intact.
- **Concurrence** : les attributions « premier arrivé » se font par `UPDATE` conditionnel atomique, jamais par « lire puis écrire ».
- `app/modules/__init__.py` est un **registre de modèles** (Alembic et les tests en dépendent) : ses imports paraissent inutilisés mais ne doivent pas être supprimés.

## Tests

Un dossier `tests/<module>/` par module (`docs/TESTS.md`). `tests/conftest.py` force `ENVIRONMENT=ci` **avant** tout import :
les tests ne peuvent pas atteindre une vraie base. Les **garde-fous structurels** font échouer la suite quand on oublie de
protéger, tracer, paginer, migrer ou documenter :

| Test | Échoue si… |
|---|---|
| `tests/core/test_authz_matrix.py` | une route n'a pas de règle d'accès déclarée, ou si un rôle a plus/moins d'accès que prévu |
| `tests/audit/test_audit_completeness.py` | une route qui écrit n'a pas de décision d'audit, ou une action du catalogue n'est jamais émise |
| `tests/core/test_openapi_contract.py` | une liste n'est pas paginée ou ses filtres ne sont pas documentés |
| `tests/core/test_migrations.py` | plusieurs têtes · un modèle a changé sans migration · une migration n'est pas rejouable |
| `tests/core/test_env_example.py` | `.env.example` et `Settings` ne sont plus synchrones |
| `tests/core/test_session_lifecycle.py` | une relation est lue après la fermeture de la session (500 en production, invisible dans les autres tests) |
| `tests/core/test_config.py` | un verrou de démarrage n'est plus appliqué |
