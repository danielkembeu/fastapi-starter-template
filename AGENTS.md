# AGENTS.md — règles impératives pour tout contributeur (humain ou IA)

Ce fichier est lu automatiquement par la plupart des assistants de code. Il s'applique **à l'identique**
à une personne. Il est volontairement court et impératif ; chaque règle renvoie au document qui l'explique.

## Avant de toucher au code

1. Lire `README.md`, puis `docs/ARCHITECTURE.md`. Pour une nouvelle ressource : `docs/AJOUTER_UN_MODULE.md`.
2. **Chercher l'existant avant d'écrire.** Le module `app/modules/projects/` est le modèle à suivre ; `app/core/` contient déjà la configuration, l'autorisation, la pagination, l'audit, l'horloge, l'e-mail, le stockage. Ne pas les réinventer.
3. Vérifier l'état de départ : `make check` doit être vert **avant** de commencer. S'il ne l'est pas, le dire — ne pas bâtir dessus.

## Règles d'architecture (non négociables)

- **Routes versionnées** : un router déclare un préfixe relatif (`/projects`) ; `app/server.py` ajoute `/api/{API_VERSION}`. Ne jamais écrire `/api/v1` dans un router (`docs/VERSIONNAGE_API.md`).
- **Un module = un dossier** `app/modules/<nom>/` avec `router.py`, `service.py`, `schemas.py`, `models.py`, `enums.py`.
- **La logique métier vit dans `service.py`**, jamais dans `router.py`. Le router déclare : route, permission, codes d'erreur, délégation.
- **Les services ne dépendent pas de `Request`.** Le contexte (IP, `X-Request-ID`) vient de `app/core/context.py`.
- **Les schémas d'entrée ne sont jamais les modèles de table.** Un schéma de sortie ne contient aucun champ sensible.
- **`app/core/` ne dépend d'aucun module métier** (sauf `security.py` et `authz.py`, qui lisent `User`).
- **Une requête = une transaction = un seul `commit()`**, après l'audit.
- Les imports de `app/modules/__init__.py` sont un **registre de modèles** : ne pas les supprimer.

## Sécurité (non négociable)

- **Toute route déclare une permission** (`Requires` / `RequiresAny` de `app/core/authz.py`). Jamais de `if user.role == …` dans un router ou un service.
- **Ressource d'autrui → 404** (et non 403) : ne pas révéler son existence.
- **Erreurs** : lever `AppError(status, ErrorCode.X, "message")`, jamais une `HTTPException` nue ni un `{"detail": …}`. Un nouveau cas d'erreur métier = un nouveau `ErrorCode` stable. Le client se base sur `code`.
- **Logs** : `logging` uniquement, un événement important porte `extra={"event": "domaine.action"}` ; niveaux : INFO normal/succès, WARNING refus ou échec géré, ERROR notre faute. Jamais d'e-mail, de mot de passe, de jeton ni de trace dans un message de log (`docs/LOGS_ET_ERREURS.md`).
- **Aucun secret** dans le code, les logs, les messages d'erreur ni les tests (hors fausses valeurs marquées `# gitleaks:allow (valeur factice de test)`).
- **Toute opération qui écrit est tracée** (`AuditService.log`, avant le `commit`) ; un refus ou un échec l'est via `log_detached`.
- **Les montants, états et propriétaires sont décidés côté serveur**, jamais fournis par le client.
- **Les attributions « premier arrivé »** se font par `UPDATE … WHERE état = attendu` + contrôle de `rowcount`, jamais « lire puis écrire ».
- **Jamais de rôle privilégié via l'API** : l'inscription crée toujours un utilisateur standard.
- **Entrées validées** : types énumérés, longueurs bornées, tri en liste blanche, `like_pattern()` pour les recherches.
- Ne jamais affaiblir une protection (verrou de démarrage, limite de débit, hook, test) pour « faire passer ». Si une protection gêne, expliquer pourquoi et demander.

## Qualité (non négociable)

- **`make check` doit être vert avant chaque commit** : ruff (lint + format), mypy (0 erreur), tests, couverture ≥ 90 %.
- **Aucun `# type: ignore`, `# noqa` ou `--no-verify` sans justification écrite** sur la même ligne. Un `# type: ignore` reste sur la ligne qu'il concerne.
- **Horloge** : `app.core.clock.utc_now()` uniquement. `datetime.now()` / `utcnow()` sont interdits (ruff `DTZ`).
- **Pas de `print()`** dans `app/` : utiliser `logging` (ruff `T20`).
- **Annotations de types complètes** dans `app/core/` ; raisonnablement complètes ailleurs. SQLModel : `col()` pour les colonnes dans `update()/delete()/ilike/in_`, `eager()` pour `selectinload`.
- **Messages utilisateur et commentaires en français** ; identifiants (variables, fonctions, fichiers) en anglais.
- Pas de code mort, pas de code commenté, pas de TODO sans ticket.
- `API_REFERENCE.md` est **généré** (`make docs`) : ne jamais l'éditer à la main.

## Tests (non négociable)

- **Tout comportement est testé, y compris ses refus.** Pour chaque route : nominal, 401/403, isolation entre utilisateurs, entrées invalides (400), conflits d'état (409).
- **Un bug corrigé a d'abord un test qui échoue** (non-régression).
- **Les garde-fous se mettent à jour avec le code** : `test_authz_matrix` (accès), `test_audit_completeness` (audit), `test_openapi_contract` (pagination), `test_session_lifecycle` (sessions réelles), `.env.example`.
- **Un test doit pouvoir échouer.** Après avoir écrit une règle, la casser volontairement pour vérifier que le test devient rouge, puis la restaurer.
- Les tests ne touchent jamais une vraie base : `ENVIRONMENT=ci` est forcé par `tests/conftest.py`.
- Ne pas supprimer ni affaiblir un test pour faire passer un changement ; corriger le code, ou expliquer pourquoi la règle change.

## Migrations (non négociable)

- **Alembic est le seul maître du schéma.** Modèle modifié ⇒ migration (`make rev m="…"`), **relue à la main**, jamais éditée après avoir été poussée.
- `downgrade()` fonctionnel **et rejouable** (supprimer aussi les types enum PostgreSQL). Une seule tête (`make heads`). `make drift` ne signale rien.
- Colonne obligatoire ajoutée à une table existante : valeur par défaut ou migration de données — jamais `nullable=False` nu.
- Voir `docs/MIGRATIONS.md`.

## Base de données — prudence

- **Avant toute commande qui écrit en base** (script, `alembic`, REPL) : vérifier la cible. Utiliser la base locale (`make up`) ou `ENVIRONMENT=ci` + `DATABASE_URL` explicite.
- **Ne jamais lancer un script destructif « pour voir ».** Les scripts écrivant en base affichent leur cible et font un **aperçu par défaut** (`--confirm` pour écrire).
- Ne jamais coller un identifiant de base réel dans un fichier, un message de commit ou un test.

## Git

- Commits atomiques, message **impératif et explicatif** (le *pourquoi*). Activer le venv avant de committer (les hooks utilisent `python -m ruff`).
- Ne pas committer de `.env*` (sauf `.env.example`), de fichier généré inutile, ni de secret.
- Ne pas pousser sur `main` directement : branche + PR (`.github/pull_request_template.md`).

## Définition de « terminé »

Un changement est terminé quand : `make check` est vert · les tests couvrent le comportement **et** ses refus ·
les garde-fous sont à jour · `.env.example` et `API_REFERENCE.md` sont à jour · la migration (si besoin) est relue et
rejouable · la documentation concernée est modifiée · **et que le résultat a été vérifié, pas seulement supposé**
(lancer les tests, lire la sortie, essayer le cas limite).

## En cas de doute

Dire ce qui est incertain plutôt que deviner. Poser la question avant une action irréversible, destructive ou
visible de l'extérieur (suppression, migration en production, publication). Rapporter fidèlement : un test rouge se
signale avec sa sortie, une étape sautée se déclare.
