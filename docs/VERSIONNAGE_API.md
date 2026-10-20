# Versionnage de l'API

> **Règle globale** : toute route métier est servie sous **`/api/{version}`** — `/api/v1/auth/login`,
> `/api/v1/projects`… La version est **une seule variable** : `API_VERSION` (défaut `v1`).

## Ce qui est versionné, et ce qui ne l'est pas

| Chemin | Versionné ? | Pourquoi |
|---|---|---|
| `/api/{version}/…` (auth, ressources, audit) | **oui** | le contrat que les clients (mobile, web) consomment |
| `/health/live`, `/startup`, `/ready` | non | lues par l'orchestrateur : elles ne doivent pas dépendre de la version d'API |
| `/docs`, `/redoc`, `/openapi.json` | non | documentation de la version servie |

## Comment c'est fait

- Les routers déclarent un préfixe **relatif** (`APIRouter(prefix="/projects")`) : ils ne connaissent pas la version.
- `app/server.py` les monte avec `prefix=settings.api_prefix` (`/api/` + `API_VERSION`) : **un seul endroit**.
- `API_VERSION` est validée au démarrage (`v1`, `v2`, `v10`… ; `latest`, `1`, `v1/`, `../x` sont refusés).
- Le schéma OAuth2 de Swagger (`tokenUrl`) suit automatiquement la version.
- `API_REFERENCE.md` (généré) affiche le préfixe en vigueur.

## Passer à une nouvelle version

**Cas simple — remplacer la version** (les clients migrent en même temps) : `API_VERSION=v2`, puis mettre à jour les
tests : `grep -rl '/api/v1' tests docs README.md | xargs sed -i 's#/api/v1#/api/v2#g'` et `make docs`.

**Cas courant — servir deux versions pendant la transition** : monter les routers deux fois, avec des préfixes différents.

```python
# app/server.py
server.include_router(router=projects_route, prefix="/api/v1")        # ancien contrat, figé
server.include_router(router=projects_v2_route, prefix="/api/v2")     # nouveau contrat
```

Créer le nouveau contrat dans de **nouveaux schémas / routers** (`projects/router_v2.py`, `schemas_v2.py`) qui réutilisent
le **même service** quand la logique ne change pas. Ainsi la version 1 reste intacte et testée.

## Quand créer une nouvelle version

| Changement | Nouvelle version ? |
|---|---|
| Ajouter une route, un champ de réponse, un paramètre **optionnel** | non (compatible) |
| Retirer ou renommer un champ/une route, changer un type, rendre un champ obligatoire, changer un code d'erreur | **oui** (cassant) |
| Corriger un bug | non (sauf si des clients dépendent du comportement erroné : le documenter) |

## Règles

1. **Une version publiée ne change plus** que par des ajouts compatibles. Les tests de la version 1 restent dans la suite tant qu'elle est servie.
2. **Annoncer et dater la fin de vie** d'une version avant de la retirer ; consigner dans un `CHANGELOG`.
3. Les garde-fous (matrice d'accès, audit, contrat OpenAPI) couvrent **chaque version montée**.
4. Les tests écrivent les chemins en dur (`/api/v1/…`) : c'est volontaire, un changement de contrat doit être **visible** dans le diff.
