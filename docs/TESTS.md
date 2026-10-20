# Tests

> **Un test qui ne peut pas échouer ne protège de rien.** Tout comportement est testé — *y compris ses refus* —
> et les règles d'architecture sont elles-mêmes des tests : oublier de protéger, tracer ou paginer une route
> fait échouer la suite.

## Lancer

| Commande | Effet |
|---|---|
| `make test` | toute la suite sur SQLite en mémoire (quelques secondes) |
| `make cov` | idem + couverture, **échoue sous 90 %** (`COV_MIN`) |
| `make test-pg` | toute la suite sur PostgreSQL local (`make up` d'abord) : enums, JSONB, déclencheur d'audit |
| `make check` | lint + types + `make cov` : ce que la CI vérifie |
| `pytest tests/projects -k status -x` | un sous-ensemble, en s'arrêtant au premier échec |

La CI lance **les deux** : SQLite avec couverture, puis PostgreSQL. SQLite est rapide mais indulgent ; PostgreSQL
révèle les types enum, JSONB, verrous et agrégations. Les tests réservés à PostgreSQL sont ignorés sur SQLite
(`tests/audit/test_audit_db.py` : le déclencheur d'ajout seul).

## Organisation

```text
tests/
 ├ conftest.py              fixtures + variables d'environnement de test
 ├ helpers/                 auth.py (comptes, jetons) · factories.py (données) · audit.py (lire le journal)
 ├ core/                    transverse : garde-fous, configuration, santé, pagination, débit, e-mail, stockage…
 ├ audit/                   service d'audit, contexte de requête, API, complétude
 ├ auth/  users/  projects/ un dossier par module
```

Un module a **son dossier de tests** : `tests/<module>/test_<module>.py`.

## Les fixtures (`tests/conftest.py`)

| Fixture | Rôle |
|---|---|
| `engine` | SQLite en mémoire, ou PostgreSQL si `TEST_DATABASE_URL` est défini ; le moteur de l'application est remplacé |
| `session` | session SQLModel sur ce moteur |
| `client` | `TestClient` dont la dépendance de session pointe sur `session` |
| `users` | fabrique de comptes : `users.user()`, `users.admin()` (+ `email=`, `status=`) |
| `rate_limit` | active le limiteur le temps d'un test, **puis restaure l'état global** |

`conftest.py` force `ENVIRONMENT=ci` **avant** tout import : les tests ne peuvent pas atteindre une vraie base
ni lire un `.env.local`. Le hachage est abaissé (`BCRYPT_ROUNDS=4`) et la limitation de débit coupée par défaut.

Helpers : `bearer(user)` donne l'en-tête `Authorization` ; `make_project(session, owner, …)` crée une donnée ;
`only(session, AuditAction.X)` lit l'unique entrée d'audit d'une action (échoue si absente ou multiple).

## Les garde-fous structurels

Ce sont des tests qui vérifient **le code lui-même**, pas un comportement.

| Test | Principe | Quand le mettre à jour |
|---|---|---|
| `core/test_authz_matrix.py` | table `EXPECTED_ACCESS` : route → rôles autorisés ; balayage avec une vraie requête par rôle | à chaque route ajoutée ou dont l'accès change |
| `audit/test_audit_completeness.py` | `MUTATING_ROUTES` : route → actions d'audit (ou exemption justifiée) ; le parcours complet doit **produire chaque action** du catalogue | à chaque route qui écrit, à chaque action ajoutée |
| `core/test_openapi_contract.py` | aucune liste brute ; paramètres `limit/offset/sort` documentés individuellement | à chaque liste ajoutée |
| `core/test_session_lifecycle.py` | une vraie session par requête → détecte les relations lues après fermeture | à chaque route de lecture ajoutée |
| `core/test_migrations.py` | une tête · modèles = migrations · retour arrière et rejeu | automatique (échoue seul) |
| `core/test_env_example.py` | `.env.example` ⇄ `Settings` | à chaque variable ajoutée |
| `core/test_config.py` | chaque verrou de démarrage | à chaque verrou ajouté |

## Quoi tester pour chaque changement

### Une route

| Cas | Attendu |
|---|---|
| nominal | code 2xx, corps conforme au schéma, effet en base |
| non authentifié | `401` |
| mauvais rôle | `403` avec le message de refus |
| ressource d'autrui | `404` (pas `403`) |
| entrée invalide (vide, trop longue, mauvais type, champ en trop sensible) | `400` |
| `PATCH {"champ": null}` sur une colonne obligatoire | `400`, pas `500` |
| transition interdite | `409` |
| effet de bord | trace d'audit avec « avant/après », notification, etc. |
| aucune trace sur échec | un refus n'écrit pas de succès (`entries(session, A.X) == []`) |

### Une liste

Pagination (`total`, `has_more`, page au-delà de la fin), chaque filtre, chaque tri autorisé, tri interdit → `400`,
recherche avec `%` littéral, filtre réservé aux administrateurs → `403`, périmètre du rôle (un utilisateur ne voit
que ses lignes).

### Une règle de sécurité

Le test décrit **l'attaque**, pas l'implémentation : « un jeton déjà tourné qui revient révoque la session »,
« un compte bloqué perd l'accès avec un jeton valide », « l'e-mail inconnu et le mauvais mot de passe sont
indiscernables ». Voir `tests/auth/test_auth.py` pour le modèle.

### Un bug corrigé

1. Écrire le test qui **reproduit** le bug et vérifier qu'il échoue pour la bonne raison.
2. Corriger. 3. Le test passe. 4. Il reste dans la suite.

### Un service tiers (e-mail, stockage, MongoDB)

Jamais d'appel réseau réel. Remplacer le client par un faux (`monkeypatch.setattr`, `sys.modules`), vérifier ce qui lui
est envoyé **et** que les erreurs sont enveloppées sans fuite (`tests/core/test_email.py`, `test_storage.py`).

## Vérifier qu'un test est utile : la mutation manuelle

Après avoir écrit une règle et son test, **casser la règle** (ouvrir une permission, retirer un `WHERE`, enlever un
`commit`) et vérifier que le test devient rouge, puis restaurer. Un test qui reste vert ne vérifie rien. Exemple
éprouvé : ajouter une colonne à un modèle sans migration doit faire échouer `test_models_and_migrations_have_not_drifted`.

## Pièges

| Piège | Règle |
|---|---|
| État global modifié par un test (limiteur, `settings`) | passer par une fixture qui **restaure**, ou `monkeypatch` |
| `settings.X` modifié directement | `monkeypatch.setattr("app.core.config.settings.X", valeur)` |
| Test qui dépend de l'ordre ou de l'heure | fabriquer ses données ; `utc_now()` ; jamais `sleep` |
| Valeur secrète factice détectée par gitleaks | `# gitleaks:allow (valeur factice de test)` |
| `datetime(...)` sans fuseau (ruff `DTZ001`) | `tzinfo=UTC`, ou `# noqa: DTZ001 — colonne UTC naïve` pour une colonne de base |
| Suite PostgreSQL lente | normal (tables recréées par test) ; itérer sur SQLite, valider sur PostgreSQL avant de pousser |

## Couverture

Seuil **90 %** (`COV_MIN`), mesuré en branches. Il **ne s'abaisse jamais** pour faire passer un changement : on
ajoute les tests. La couverture dit ce qui n'est *pas* testé, pas que le reste est *bien* testé : elle ne remplace
ni les refus, ni l'isolation, ni la mutation manuelle.
