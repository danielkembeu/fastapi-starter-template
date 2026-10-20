# Ajouter un module (pas à pas)

Le module `projects` est l'**exemple de référence** : il montre l'appartenance (`own` / `all`), une machine
à états, une liste filtrée et paginée, l'audit et les tests. Copiez-le.

## Checklist

1. **Dossier** `app/modules/<nom>/` avec `__init__.py`, `enums.py`, `models.py`, `schemas.py`, `service.py`, `router.py`.
2. **Modèle** : hériter de `SQLModel, table=True`, `__tablename__`, clé `UUID`, `created_at` indexé. Déclarer les relations des deux côtés (`TYPE_CHECKING` pour éviter les imports circulaires).
3. **Registre** : importer le modèle dans `app/modules/__init__.py`.
4. **Permissions** (`app/core/authz.py`) : ajouter `Permission.<X>_CREATE / _READ_OWN / _READ_ALL / …`, les attribuer dans `ROLE_PERMISSIONS`.
5. **Schémas** : un schéma d'entrée par action (jamais le modèle de table), un schéma de sortie sans champ sensible, un modèle de filtres héritant de `PageQuery` avec `sort` en `Literal[...]`.
6. **Service** : toute la logique. Règles : contrôler la portée (`ensure_owner_or_permission`), répondre **404** pour la ressource d'autrui, valider les transitions d'état, **un seul `commit()`**, appeler `AuditService.log(...)` **avant** le commit.
7. **Router** : `Requires(...)` / `RequiresAny(...)`, `responses=err(...)`, `response_model=Page[...]` pour les listes. Le brancher dans `app/server.py`.
8. **Audit** : ajouter les actions à `AuditAction` (`app/modules/audit/enums.py`) et le type de ressource à `RESOURCE_TYPES` (`audit/service.py`).
9. **Migration** : `make rev m="ajout <nom>"`, **relire** le fichier généré (enums PostgreSQL à supprimer dans `downgrade`), `make migrate`, `make drift` (doit être vide).
10. **Tests** (obligatoires, ils sont exigés par les garde-fous) :
    - `tests/core/test_authz_matrix.py` : déclarer chaque route dans `EXPECTED_ACCESS` ;
    - `tests/audit/test_audit_completeness.py` : déclarer chaque route dans `MUTATING_ROUTES` et faire produire les nouvelles actions par le parcours complet ;
    - `tests/core/test_openapi_contract.py` : ajouter les listes paginées attendues ;
    - `tests/core/test_session_lifecycle.py` : ajouter les routes de lecture ;
    - `tests/<nom>/test_<nom>.py` : nominal, **403**, **isolation entre utilisateurs**, entrées invalides (**400**), transitions interdites (**409**), pagination/filtres, trace d'audit.
11. `make docs` puis `make check`.

## Les pièges classiques

| Piège | Règle |
|---|---|
| Route statique masquée par une route dynamique (`/history` vs `/{id}`) | déclarer les routes statiques **avant** les dynamiques |
| `PATCH` avec `null` explicite sur une colonne obligatoire → 500 | refuser en **400** (`if data[field] is None`) |
| Attribuer « le premier qui demande » | `UPDATE … WHERE état = attendu` et vérifier `rowcount` ; jamais lire puis écrire |
| Audit « avant » pris après les effets de bord | `AuditService.snapshot(...)` **avant** de modifier |
| Tri sur un champ libre | liste blanche (`Literal` + `apply_sort`), départage par `id` |
| Recherche avec `%` / `_` | `like_pattern()` les échappe |
| `datetime.now()` pour une date ou une expiration | `utc_now()` (`app/core/clock.py`) ; ruff `DTZ` l'interdit |
| Relation lue après fermeture de session | charger explicitement (`eager(...)`) et couvrir par `test_session_lifecycle` |

## Retirer l'exemple `projects`

Supprimer :

- `app/modules/projects/` et `tests/projects/` ;
- sa ligne dans `app/modules/__init__.py`, son import et son `include_router` dans `app/server.py` ;
- les permissions `PROJECT_*` et leur attribution (`app/core/authz.py`) ;
- les actions `PROJECT_*` (`app/modules/audit/enums.py`) et `"Project"` dans `RESOURCE_TYPES` (`audit/service.py`) ;
- la relation `projects` du modèle `User` (`app/modules/users/models.py`) ;
- `make_project` (`tests/helpers/factories.py`) ;
- ses lignes dans `tests/core/test_authz_matrix.py`, `tests/audit/test_audit_completeness.py`, `tests/core/test_openapi_contract.py`, `tests/core/test_session_lifecycle.py`, et les tests de `tests/core/test_pagination.py` qui l'utilisent (les remplacer par votre première ressource) ;
- la table `projects` dans la migration initiale, **ou** une nouvelle migration qui la supprime (`make rev`).

Puis `make check` : les garde-fous signalent tout ce qui reste.
