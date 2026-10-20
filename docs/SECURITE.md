# Sécurité : ce qui est en place, et ce qui reste

Ce document décrit le modèle de sécurité **tel qu'implémenté**, chaque mesure renvoyant au test qui la protège.
La dernière section liste ce qui n'est **pas** couvert. Principe directeur : **refuser de démarrer ou de servir plutôt
que de fonctionner de façon dangereuse**.

## 1. Configuration et démarrage

| Mesure | Détail | Test |
|---|---|---|
| Verrous de démarrage | secret faible, base locale en production, CORS `*`, e-mail `console` ou stockage `local` en production, paramètres manquants du backend choisi : **l'application ne démarre pas** et liste tous les problèmes | `tests/core/test_config.py` |
| Base distante interdite en local | un poste de développement ne peut pas écrire dans une base de production par accident | `test_local_*` |
| Aucun secret dans l'image | `.dockerignore` exclut tous les `.env*` ; variables injectées | — |
| Secrets jamais committés | `gitleaks` + `detect-private-key` au commit ; `.env*` ignorés par git | hooks |
| `.env.example` = documentation exacte | synchronisé avec `Settings` | `tests/core/test_env_example.py` |

## 2. Autorisation (RBAC)

Voir `docs/ARCHITECTURE.md`. Tout est dans `app/core/authz.py`. Garde-fou : `tests/core/test_authz_matrix.py` balaie
**toutes les routes** avec une vraie requête par rôle contre une table déclarative ; une route sans règle déclarée fait
échouer la suite. **Aucune route ne crée un administrateur** : seul `scripts/create_admin.py` le fait.

## 3. Authentification et sessions

| Mesure | Détail | Test |
|---|---|---|
| Mots de passe hachés | bcrypt ; 8+ caractères, une lettre, un chiffre | `test_register_rejects_weak_passwords` |
| Refresh tokens **hachés** | SHA-256 en base : une fuite de la base ne donne aucune session | `test_refresh_token_is_stored_hashed_never_in_clear` |
| Rotation + détection de vol | un jeton déjà tourné qui revient révoque toute la session | `test_reusing_a_rotated_refresh_token_revokes_the_session` |
| Anti brute-force par compte | `MAX_LOGIN_ATTEMPTS` échecs → verrou `LOGIN_LOCK_MINUTES` (`429` + `Retry-After`) | `test_account_locks_after_repeated_failures…` |
| Anti brute-force par IP | `/login` : `RATE_LIMIT_AUTH` ; `/register` : `RATE_LIMIT_REGISTER` | `test_login_is_rate_limited_per_ip` |
| Pas d'énumération de comptes | e-mail inconnu et mauvais mot de passe : même `401`, même message, même temps de calcul | `test_unknown_email_and_wrong_password_are_indistinguishable` |
| Jeton d'accès court | 15 min par défaut, expiration en UTC | `test_expired_access_token_is_rejected` |
| Compte bloqué = accès coupé tout de suite | le statut est relu en base à chaque requête, même avec un jeton valide | `test_blocking_an_account_cuts_access_immediately…` |
| Sessions limitées | `MAX_SESSIONS_PER_USER`, les plus anciennes supprimées | `test_sessions_per_user_are_capped…` |
| E-mail normalisé | minuscules, unicité insensible à la casse | `test_register_duplicate_email_returns_409_ignoring_case` |
| Rôle non choisissable | l'inscription crée toujours un utilisateur standard | `test_register_creates_a_standard_user_never_an_admin` |
| Inscription fermable | `REGISTRATION_ENABLED=false` → `403` | `test_registration_can_be_closed_by_configuration` |
| Politique de mot de passe partout | l'administrateur créé par script suit la même règle | `tests/users/test_create_admin.py` |

> bcrypt tronque silencieusement au-delà de 72 octets : deux mots de passe partageant les 72 premiers octets sont équivalents.

## 4. Limitation de débit

Middleware (`app/core/ratelimit.py`), compteur par utilisateur authentifié, sinon par IP. **Fail-open** : si Redis tombe,
les limites sont suspendues plutôt que de couper l'API. `memory://` compte **par processus** : avec plusieurs workers,
utiliser Redis (`RATE_LIMIT_STORAGE_URI=redis://…`). Un avertissement est journalisé en production avec `memory://`.

## 5. Entrées, fichiers et e-mails

| Risque | Protection | Test |
|---|---|---|
| Fichier téléversé géant / de type interdit / **faux type** | taille max, liste blanche, **vérification de la signature réelle** | `tests/core/test_storage.py` |
| Traversée de répertoire par nom de fichier ou de dossier | nom aléatoire, chemin résolu sous la racine | `test_a_hostile_folder_cannot_escape…` |
| Injection d'en-têtes d'e-mail (`Bcc:` caché) | retours à la ligne refusés dans destinataire et sujet | `test_header_injection_is_refused` |
| Fuite d'identifiants SMTP dans les logs | erreur générique, message du serveur jamais journalisé | `test_a_smtp_failure_raises_a_generic_error…` |
| Injection de jokers dans une recherche | `like_pattern()` échappe `%` et `_` | `tests/core/test_pagination.py` |
| Tri sur un champ sensible | liste blanche + `400` | `test_sort_direction_and_whitelist` |
| `PATCH` avec `null` sur une colonne obligatoire | `400`, pas `500` | `test_a_null_name_is_refused_instead_of_crashing` |

## 6. Données et exposition

- **Suppression logique** des comptes ; **ressource d'autrui = 404** (on ne révèle pas son existence).
- **Horloge UTC unique** (`utc_now()`), `datetime.now()` interdit par le lint.
- `/docs` et `/openapi.json` : ouverts en local/ci, HTTP Basic en staging, **404 en production**.
- Image Docker non-root, aucun `.env` embarqué, `--no-server-header`, Sentry sans données personnelles.
- Sondes `/health/*` : le public ne voit que `ok`/`down` ; le détail exige `X-Health-Token`.
- Erreurs `500` génériques ; `X-Request-ID` pour retrouver l'erreur sans exposer de détail.
- **Journal d'audit** de toutes les opérations : `docs/AUDIT.md`.
- Lint de sécurité (ruff `S`, bandit) et `pip-audit` en CI.

## 7. Ce qui n'est PAS couvert (à décider selon le projet)

| Sujet | Remarque |
|---|---|
| Vérification de l'e-mail / du téléphone | absente : sans elle, n'importe qui s'inscrit avec l'e-mail d'un tiers |
| Réinitialisation de mot de passe | absente (dépend de votre circuit d'e-mails ou d'une validation par un administrateur) |
| Changement de mot de passe, gestion des sessions par l'utilisateur | absents (retirés pour garder le socle minimal) |
| Double authentification | absente ; à envisager pour les comptes d'administration |
| Révocation d'un jeton d'accès avant expiration | impossible (≤ `ACCESS_TOKEN_EXPIRE_MINUTES`) ; un compte *bloqué* est coupé immédiatement |
| Analyse antivirus / ré-encodage des fichiers | non fournis (voir `docs/INTEGRATIONS.md`) |
| Rotation des secrets | manuelle |
| Conservation du journal d'audit | sans purge (volontaire) ; prévoir un archivage |
| `pip-audit` | informatif en CI ; à rendre bloquant en production |
| Injection NoSQL (MongoDB) | à traiter dans vos modules (ne jamais passer une entrée brute comme filtre) |
