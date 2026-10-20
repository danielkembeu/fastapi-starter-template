# Pagination, filtres et tri

Tout endpoint qui renvoie une collection suit **le même contrat**. Aucune route ne renvoie une table
entière : c'est ce qui garde l'API rapide quand les données grossissent.

Règle vérifiée automatiquement : `tests/core/test_openapi_contract.py` échoue si une route `GET` renvoie
une liste brute.

## Le contrat

### Paramètres (identiques partout)

| Paramètre | Défaut | Règle | Rôle |
|---|---|---|---|
| `limit` | 20 | 1 à 100 | éléments par page |
| `offset` | 0 | ≥ 0 | éléments à sauter |
| `sort` | propre à l'endpoint | valeur de la liste blanche | champ de tri ; préfixe `-` = décroissant |

Une valeur hors limites (`limit=0`, `limit=500`, `offset=-1`, `sort=password`) renvoie **400**.

### Réponse (identique partout)

```json
{ "items": [ { "...": "..." } ], "total": 137, "limit": 20, "offset": 40, "has_more": true }
```

| Champ | Sens |
|---|---|
| `items` | les éléments de la page |
| `total` | éléments correspondant aux filtres (pas la taille de la table) |
| `limit`, `offset` | rappel de la page demandée |
| `has_more` | `true` s'il reste des éléments après cette page |

### Garanties

- **Pas de doublon ni d'oubli entre deux pages** : le tri est toujours départagé par l'identifiant.
- **Tri en liste blanche** : jamais sur un champ sensible.
- **La recherche `q` traite `%` et `_` littéralement.**
- **Bornes de dates** `created_from` / `created_to` inclusives ; `created_from` > `created_to` renvoie 400.

### Limite connue de `limit/offset`

Si des éléments sont **ajoutés en tête** pendant la pagination (flux alimenté en continu), la page suivante
peut répéter un élément déjà vu. Côté client, dédoublonner par `id`. À très grande échelle, préférer une
pagination par curseur.

## Filtres des endpoints fournis

| Endpoint | Accès | Filtres | `sort` (défaut en gras) |
|---|---|---|---|
| `GET /api/v1/projects` | utilisateur (les siens) · admin (tous) | `q` (nom), `status`, `owner_id` (admin seulement : **403** sinon), `created_from`, `created_to` | **`-created_at`**, `created_at`, `name`, `-name` |
| `GET /api/v1/admin/audit-logs` | admin | `actor_id`, `action`, `resource_type`, `resource_id`, `outcome`, `request_id`, `created_from`, `created_to` | **`-created_at`**, `created_at` |

Le **périmètre dépend du rôle** : un filtre réservé aux administrateurs renvoie **403** aux autres rôles
plutôt que d'être ignoré silencieusement.

## Ajouter une liste paginée

1. Le modèle de filtres hérite de `PageQuery` (`app/core/pagination.py`) ; il doit être **le seul** paramètre de requête de la route, sinon Swagger ne développe pas les filtres.
2. Le service construit la requête filtrée, applique `apply_sort(...)` avec une **liste blanche** et un départage par `id`, puis `paginate(session, stmt, params)`.
3. Le router déclare `response_model=Page[MonSchema]` et appelle `Service.list(session, filters.page, filters)`.
4. Index sur les colonnes filtrées/triées (migration).
5. `make docs` ; `test_openapi_contract.py` vérifie le contrat (ajouter la route à la liste attendue).
