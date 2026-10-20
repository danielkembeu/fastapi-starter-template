# Référence de l'API

> **Document généré automatiquement** par `python -m scripts.generate_api_reference` à partir du code
> (schéma OpenAPI + matrice des rôles). Ne pas modifier à la main : `make docs` le régénère et la CI
> vérifie qu'il est à jour.

## Conventions générales

| Sujet | Règle |
|---|---|
| Base URL | `https://<domaine>` — toutes les routes métier sont sous `/api/v1` (version : `API_VERSION`) ; les sondes `/health` ne sont pas versionnées |
| Authentification | `Authorization: Bearer <access_token>` (obtenu par `POST /api/v1/auth/login`) |
| Format | JSON, dates ISO 8601, identifiants UUID |
| Erreurs | toujours `{"error": {"code", "message", "status", "request_id", "details"}}` : se baser sur `code` (stable), jamais sur `message` ; `request_id` à communiquer au support (voir `docs/LOGS_ET_ERREURS.md`) |
| Validation | une entrée invalide renvoie **400** (et non 422) |
| PATCH | partiel : seuls les champs envoyés sont modifiés |
| Rôles | `utilisateur` (user), `admin` |

### Listes paginées

Tous les endpoints qui renvoient une collection sont paginés, filtrables et triables (voir `docs/PAGINATION.md`).

| Paramètre | Défaut | Règle |
|---|---|---|
| `limit` | 20 | 1 à 100 |
| `offset` | 0 | ≥ 0 |
| `sort` | variable | champ de la liste blanche de l'endpoint ; préfixe `-` pour décroissant |

Réponse : `{"items": [...], "total": N, "limit": L, "offset": O, "has_more": true|false}`

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

## Sommaire

- **Authentication** — 5 route(s)
- **Projects** — 6 route(s)
- **Audit** — 1 route(s)

## Authentication

### `POST /api/v1/auth/register`

Inscrit un nouvel utilisateur (le rôle est toujours `user`).

Mot de passe : 8 caractères minimum, au moins une lettre et un chiffre. L'e-mail est
normalisé en minuscules. Le client doit ensuite appeler `/login` pour obtenir des jetons.
Limite : `RATE_LIMIT_REGISTER` par adresse IP.

**Accès** : public (aucun jeton)

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `email` | string (email) | oui |  |  |
| `password` | string | oui |  |  |
| `first_name` | string | oui |  | longueur min 1, longueur max 80 |
| `last_name` | string | oui |  | longueur min 1, longueur max 80 |

**Réponse 201** — `UserRegisterResponse`

| Champ | Type |
|---|---|
| `success` | boolean |
| `message` | string |
| `user` | UserRead |

**Erreurs possibles** : `400`, `403`, `409`, `429`, `500`

### `POST /api/v1/auth/login`

Authentifie un utilisateur (email + mot de passe) et émet ses jetons.

`device` est dérivé de l'en-tête `User-Agent`, `ip_address` de la connexion. Retourne un
`access_token` (à mettre dans `Authorization: Bearer …`) et un `refresh_token` à conserver.

Protections : 401 identique pour e-mail inconnu et mauvais mot de passe ; verrouillage du
compte après `MAX_LOGIN_ATTEMPTS` échecs (429 + `Retry-After`) ; limite par adresse IP.

**Accès** : public (aucun jeton)

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `email` | string | oui |  | longueur min 1, longueur max 254 |
| `password` | string | oui |  | longueur min 1, longueur max 1024 |

**Réponse 200** — `LoginResponse`

| Champ | Type |
|---|---|
| `access_token` | string |
| `refresh_token` | string |
| `token_type` | string |
| `user` | UserRead |

**Erreurs possibles** : `400`, `401`, `403`, `429`, `500`

### `POST /api/v1/auth/refresh`

Régénère un nouvel access_token et refresh_token.

Le refresh_token courant est **invalidé** (rotation). Présenter à nouveau un jeton déjà
utilisé révoque la session (détection de vol). 401 si le jeton est inconnu, expiré, ou si
le compte n'est plus actif.

**Accès** : public (aucun jeton)

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `refresh_token` | string | oui |  | longueur min 1, longueur max 512 |
| `device` | string (nullable) | non |  | longueur max 255 |
| `ip_address` | string (nullable) | non |  | Ignoré : l'adresse IP est lue côté serveur. |

**Réponse 200** — `LoginResponse`

| Champ | Type |
|---|---|
| `access_token` | string |
| `refresh_token` | string |
| `token_type` | string |
| `user` | UserRead |

**Erreurs possibles** : `400`, `401`, `429`, `500`

### `POST /api/v1/auth/logout`

Déconnecte la session associée au refresh_token fourni.

**Accès** : public (aucun jeton)

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `refresh_token` | string | oui |  | longueur min 1, longueur max 512 |

**Réponse 200** — `LogoutResponse`

| Champ | Type |
|---|---|
| `success` | boolean |
| `message` | string |

**Erreurs possibles** : `400`, `404`, `500`

### `GET /api/v1/auth/me`

Renvoie l'utilisateur authentifié, déduit de l'access_token.

**Accès** : tout utilisateur connecté

**Réponse 200** — `UserRead`

| Champ | Type |
|---|---|
| `id` | string (uuid) |
| `email` | string |
| `first_name` | string |
| `last_name` | string |
| `role` | UserRole |
| `status` | UserStatus |
| `created_at` | string (date-time) |
| `updated_at` | string (date-time) (nullable) |

**Erreurs possibles** : `400`, `401`, `403`, `500`

## Projects

### `GET /api/v1/projects`

Liste paginée des projets : les siens, ou tous pour un administrateur.

Filtres : `q`, `status`, `owner_id` (admin), `created_from`, `created_to` ; tri : `sort`.

**Accès** : tout utilisateur connecté

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `limit` | requête | integer | non | `20` | Nombre maximal d'éléments (1 à 100).; min 1, max 100 |
| `offset` | requête | integer | non | `0` | Nombre d'éléments à sauter.; min 0 |
| `q` | requête | string (nullable) | non |  | Recherche dans le nom.; longueur max 80 |
| `status` | requête | ProjectStatus (nullable) | non |  |  |
| `owner_id` | requête | string (uuid) (nullable) | non |  | Réservé aux administrateurs (403 sinon). |
| `created_from` | requête | string (date-time) (nullable) | non |  |  |
| `created_to` | requête | string (date-time) (nullable) | non |  |  |
| `sort` | requête | `created_at` \| `-created_at` \| `name` \| `-name` | non | `-created_at` |  |

**Réponse 200** — `Page_ProjectRead_`

| Champ | Type |
|---|---|
| `items` | liste de ProjectRead |
| `total` | integer |
| `limit` | integer |
| `offset` | integer |
| `has_more` | boolean |

**Erreurs possibles** : `400`, `401`, `403`, `500`

### `POST /api/v1/projects`

Crée un projet (statut `draft`) appartenant à l'utilisateur authentifié.

**Accès** : utilisateur

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `name` | string | oui |  | longueur min 1, longueur max 120 |
| `description` | string (nullable) | non |  | longueur max 2000 |

**Réponse 201** — `ProjectRead`

| Champ | Type |
|---|---|
| `id` | string (uuid) |
| `owner_id` | string (uuid) |
| `name` | string |
| `description` | string (nullable) |
| `status` | ProjectStatus |
| `created_at` | string (date-time) |
| `updated_at` | string (date-time) (nullable) |

**Erreurs possibles** : `400`, `401`, `403`, `500`

### `GET /api/v1/projects/{project_id}`

Renvoie un projet. 404 si ce n'est pas le sien (sauf administrateur).

**Accès** : tout utilisateur connecté

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `project_id` | chemin | string (uuid) | oui |  |  |

**Réponse 200** — `ProjectRead`

| Champ | Type |
|---|---|
| `id` | string (uuid) |
| `owner_id` | string (uuid) |
| `name` | string |
| `description` | string (nullable) |
| `status` | ProjectStatus |
| `created_at` | string (date-time) |
| `updated_at` | string (date-time) (nullable) |

**Erreurs possibles** : `400`, `401`, `403`, `404`, `500`

### `PATCH /api/v1/projects/{project_id}`

Modifie le nom ou la description. 409 si le projet est archivé.

**Accès** : tout utilisateur connecté

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `project_id` | chemin | string (uuid) | oui |  |  |

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `name` | string (nullable) | non |  | longueur min 1, longueur max 120 |
| `description` | string (nullable) | non |  | longueur max 2000 |

**Réponse 200** — `ProjectRead`

| Champ | Type |
|---|---|
| `id` | string (uuid) |
| `owner_id` | string (uuid) |
| `name` | string |
| `description` | string (nullable) |
| `status` | ProjectStatus |
| `created_at` | string (date-time) |
| `updated_at` | string (date-time) (nullable) |

**Erreurs possibles** : `400`, `401`, `403`, `404`, `409`, `500`

### `POST /api/v1/projects/{project_id}/status`

Change le statut : `draft → active | archived`, `active → archived`. 409 sinon.

**Accès** : tout utilisateur connecté

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `project_id` | chemin | string (uuid) | oui |  |  |

**Corps JSON**

| Champ | Type | Requis | Défaut | Détail |
|---|---|---|---|---|
| `status` | ProjectStatus | oui |  |  |

**Réponse 200** — `ProjectRead`

| Champ | Type |
|---|---|
| `id` | string (uuid) |
| `owner_id` | string (uuid) |
| `name` | string |
| `description` | string (nullable) |
| `status` | ProjectStatus |
| `created_at` | string (date-time) |
| `updated_at` | string (date-time) (nullable) |

**Erreurs possibles** : `400`, `401`, `403`, `404`, `409`, `500`

### `DELETE /api/v1/projects/{project_id}`

Supprime un projet (le journal d'audit en garde la trace).

**Accès** : tout utilisateur connecté

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `project_id` | chemin | string (uuid) | oui |  |  |

**Réponse 204** — sans corps

**Erreurs possibles** : `400`, `401`, `403`, `404`, `500`

## Audit

### `GET /api/v1/admin/audit-logs`

Journal d'audit : toutes les opérations, les plus récentes d'abord (administrateurs uniquement).

Le journal est en **ajout seul** : aucune route ne permet de modifier ou supprimer une entrée.
Filtres utiles : `resource_type` + `resource_id` (historique complet d'une ressource),
`actor_id` (tout ce qu'un utilisateur a fait), `action`, `outcome` (`denied`/`failed` pour les
incidents), `request_id` (tout ce qu'une requête a déclenché). Consulter le journal est lui-même journalisé.

**Accès** : admin

**Paramètres**

| Nom | Où | Type | Requis | Défaut | Détail |
|---|---|---|---|---|---|
| `limit` | requête | integer | non | `20` | Nombre maximal d'éléments (1 à 100).; min 1, max 100 |
| `offset` | requête | integer | non | `0` | Nombre d'éléments à sauter.; min 0 |
| `actor_id` | requête | string (uuid) (nullable) | non |  | Les opérations d'un utilisateur. |
| `action` | requête | AuditAction (nullable) | non |  | Une action précise, ex. `project.created`. |
| `resource_type` | requête | string (nullable) | non |  | `project`, `user`, `session`…; longueur max 40 |
| `resource_id` | requête | string (uuid) (nullable) | non |  | L'historique complet d'une ressource. |
| `outcome` | requête | AuditOutcome (nullable) | non |  |  |
| `request_id` | requête | string (nullable) | non |  | Toutes les entrées d'une même requête.; longueur max 64 |
| `created_from` | requête | string (date-time) (nullable) | non |  | À partir de (UTC, inclus). |
| `created_to` | requête | string (date-time) (nullable) | non |  | Jusqu'à (UTC, inclus). |
| `sort` | requête | `-created_at` \| `created_at` | non | `-created_at` |  |

**Réponse 200** — `Page_AuditLogRead_`

| Champ | Type |
|---|---|
| `items` | liste de AuditLogRead |
| `total` | integer |
| `limit` | integer |
| `offset` | integer |
| `has_more` | boolean |

**Erreurs possibles** : `400`, `401`, `403`, `500`
