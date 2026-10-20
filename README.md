# FastAPI Backend Template

Socle backend **sécurisé, testé et fiable** pour des projets métier : FastAPI · SQLModel · PostgreSQL (ou MongoDB) · Alembic.

Il ne contient **aucun métier**. Il contient ce qui ne se rattrape jamais bien après coup : la
configuration par environnement, l'authentification, l'autorisation, la traçabilité, la qualité de code,
les tests, les migrations et le pipeline de livraison. Vous ajoutez vos modules par-dessus.

> **Trois valeurs non négociables** — elles sont appliquées par des **tests et des hooks**, pas par de la bonne volonté :
> 1. **Sécurité** : on refuse de démarrer plutôt que de servir avec une configuration dangereuse.
> 2. **Tests** : tout comportement est testé, *y compris les refus* ; les garde-fous structurels font échouer la suite si on oublie quelque chose.
> 3. **Fiabilité** : une seule façon de faire les choses (architecture, migrations, horloge UTC, erreurs), vérifiée automatiquement.

---

## Sommaire

1. [Ce que contient le template (et ce qu'il ne contient pas)](#1-ce-que-contient-le-template-et-ce-quil-ne-contient-pas)
2. [Démarrer en 5 minutes](#2-démarrer-en-5-minutes)
3. [Structure du projet](#3-structure-du-projet)
4. [Configuration](#4-configuration)
5. [Les garde-fous](#5-les-garde-fous)
6. [Commandes](#6-commandes)
7. [Qualité, hooks et pipeline](#7-qualité-hooks-et-pipeline)
8. [Travailler ici : en humain ou avec une IA](#8-travailler-ici--en-humain-ou-avec-une-ia)
9. [Documentation](#9-documentation)
10. [Créer un projet à partir du template](#10-créer-un-projet-à-partir-du-template)
11. [Limites assumées](#11-limites-assumées)

---

## 1. Ce que contient le template (et ce qu'il ne contient pas)

### Endpoints fournis — volontairement peu

| Groupe | Routes | Rôle |
|---|---|---|
| **Versionnage** | toutes les routes métier sous `/api/{version}` (`API_VERSION=v1`) | règle globale, voir `docs/VERSIONNAGE_API.md` |
| **Santé** | `GET /health/live`, `/startup`, `/ready` | sondes pour l'orchestrateur |
| **Authentification** | `POST /api/v1/auth/register`, `/login`, `/refresh`, `/logout` · `GET /api/v1/auth/me` | authentification minimale **mais réelle** (pas de simulation) |
| **Exemple** | `/api/v1/projects` (liste, création, lecture, modification, changement de statut, suppression) | **modèle à copier** pour vos ressources, à supprimer ensuite |
| **Supervision** | `GET /api/v1/admin/audit-logs` | lecture du journal d'audit (administrateurs) |

Le premier administrateur se crée par script (`make create-admin`) : **aucune route ne peut créer un rôle privilégié**.

### Infrastructure fournie

| Domaine | Ce qui est en place |
|---|---|
| **Configuration** | variables pour **tous les cas** (ports, PostgreSQL/MongoDB, Redis, SMTP, Cloudinary/S3, Sentry, CORS, limites de débit…) dans `.env.example`, typées dans `app/core/config.py`, avec des **verrous de démarrage** par environnement |
| **Bases de données** | `DATABASE_BACKEND=postgres` (SQLModel + Alembic) ou `mongodb` (PyMongo) — voir [`docs/BASES_DE_DONNEES.md`](docs/BASES_DE_DONNEES.md) |
| **E-mail** | `console` (dev) · `smtp` (réel) · `disabled`, protégé contre l'injection d'en-têtes |
| **Fichiers** | `local` (dev) · `cloudinary` · `s3` (AWS, MinIO, R2…), avec validation de taille, de type **et de signature réelle** |
| **Autorisation** | RBAC (rôles → permissions → portée) dans **un seul fichier** |
| **Authentification** | JWT court, refresh token **haché** avec rotation et détection de vol, verrouillage anti brute-force, pas d'énumération de comptes |
| **Audit** | journal **en ajout seul** (déclencheur PostgreSQL), atomique avec l'opération, secrets masqués |
| **API** | pagination unique `{items,total,limit,offset,has_more}`, tri en liste blanche, **erreurs structurées** (`code` stable, `message`, `details`, `request_id`), limitation de débit (Redis, *fail-open*) |
| **Logs** | JSON structuré en staging/production, texte lisible en local ; **niveau, format et traces d'appels réglés par environnement** ; secrets masqués ; une ligne d'accès par requête |
| **Exploitation** | `X-Request-ID` relié aux logs, à Sentry, à l'audit et à la réponse d'erreur ; `Dockerfile` non-root ; `docker-compose` de développement |

### Ce qu'il ne contient pas (à vous d'ajouter)

Votre métier · une interface d'administration · la vérification d'e-mail et la réinitialisation de mot de
passe · la double authentification · les tâches de fond · le temps réel. La liste honnête des manques de
sécurité est dans [`docs/SECURITE.md`](docs/SECURITE.md).

---

## 2. Démarrer en 5 minutes

Prérequis : Python 3.12+, Docker ou Podman (avec `compose`).

```bash
python -m venv env && source env/bin/activate     # le venv doit être ACTIF pour les hooks git
make install                                       # dépendances applicatives et de développement
make up                                            # PostgreSQL local (127.0.0.1:55432) : bases app_dev et app_test
cp .env.example .env.local                         # puis renseigner SECRET_JWT (commande indiquée dans le fichier)
make migrate                                       # applique les migrations Alembic
make create-admin EMAIL=admin@example.com FIRST=Ada LAST=Admin            # aperçu : montre la base visée
make create-admin EMAIL=admin@example.com FIRST=Ada LAST=Admin CONFIRM=1 # écrit réellement
make dev                                           # http://127.0.0.1:8000/docs
make hooks                                         # installe les hooks git (commit rapide, push complet)
make check                                         # lint + types + tests + couverture : TOUT doit être vert
```

Services optionnels de développement : `make up PROFILES="cache mail"` (Redis, boîte mail captant les
e-mails), `PROFILES="mongo storage"` (MongoDB, stockage S3 MinIO). Les ports se règlent dans `.env.local`.

---

## 3. Structure du projet

```text
app/
 ├ server.py              point d'entrée : middlewares, erreurs, routers (montés selon le backend)
 ├ core/                  infrastructure transverse — aucune règle métier
 │   config · authz · security · clock · pagination · ratelimit · health · context · logging
 │   docs · errors · database · mongo · email · storage · sql · validators
 └ modules/<feature>/     UN module = UN dossier autonome
     router.py · service.py · schemas.py · models.py · enums.py
     auth · users · audit · projects (exemple)
alembic/                  migrations — SEUL maître du schéma
scripts/                  create_admin · generate_api_reference
tests/<feature>/          un dossier de tests par module · tests/core pour le transverse
docs/                     documentation détaillée (voir §9)
.github/                  CI, déploiement, Dependabot, modèle de PR
```

**Règle d'architecture** : la logique métier vit dans `service.py`, jamais dans `router.py`. Détail : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 4. Configuration

Tout se règle par variables d'environnement (`.env.example` les documente **toutes**, par groupe).

| Groupe | Variables principales | Sélection |
|---|---|---|
| Logs et erreurs | `LOG_LEVEL`, `LOG_FORMAT`, `LOG_STACKTRACES`, `ERROR_DEBUG` | — |
| Application | `ENVIRONMENT`, `API_VERSION`, `APP_HOST`, `APP_PORT`, `APP_PUBLIC_URL`, `LOG_LEVEL`, `REGISTRATION_ENABLED` | `ENVIRONMENT` = `local` · `ci` · `staging` · `production` |
| Base de données | `DATABASE_URL`, `MONGODB_URL`, `MONGODB_DB_NAME`, `DB_POOL_SIZE` | `DATABASE_BACKEND` = `postgres` · `mongodb` |
| Authentification | `SECRET_JWT`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `MAX_LOGIN_ATTEMPTS`, `MAX_SESSIONS_PER_USER` | — |
| Réseau | `CORS_ORIGINS`, `DOCS_USERNAME`, `FORWARDED_ALLOW_IPS`, `WEB_CONCURRENCY` | — |
| Redis / débit | `REDIS_URL`, `RATE_LIMIT_STORAGE_URI`, `RATE_LIMIT_*` | — |
| E-mail | `EMAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | `EMAIL_BACKEND` = `console` · `smtp` · `disabled` |
| Fichiers | `UPLOAD_MAX_BYTES`, `CLOUDINARY_*`, `S3_*` | `STORAGE_BACKEND` = `disabled` · `local` · `cloudinary` · `s3` |
| Supervision | `SENTRY_DSN`, `HEALTH_DETAIL_TOKEN` | — |

**Verrous de démarrage** — l'application refuse de démarrer, en listant *tous* les problèmes :
secret JWT faible · base distante en local · base locale en production · CORS `*` · e-mail `console` ou
stockage `local` en production · paramètres manquants pour le backend choisi (SMTP, S3, Cloudinary, MongoDB…).
Détail : [`docs/ENVIRONNEMENTS.md`](docs/ENVIRONNEMENTS.md).

---

## 5. Les garde-fous

Ce sont des **tests** : oublier une règle fait échouer `make check` (donc le push, donc la CI).

| Garde-fou | Échoue si… |
|---|---|
| `tests/core/test_authz_matrix.py` | une route n'a pas de règle d'accès déclarée, ou si un rôle a plus/moins d'accès que prévu |
| `tests/audit/test_audit_completeness.py` | une route qui écrit n'a pas de décision d'audit, ou si une action du catalogue n'est jamais émise |
| `tests/core/test_openapi_contract.py` | une liste n'est pas paginée ou ses filtres ne sont pas documentés |
| `tests/core/test_migrations.py` | plusieurs têtes Alembic · un modèle a changé sans migration · une migration n'est pas rejouable |
| `tests/core/test_env_example.py` | `.env.example` et `Settings` ne sont plus synchrones |
| `tests/core/test_config.py` | un verrou de démarrage n'est plus appliqué |
| `tests/core/test_session_lifecycle.py` | une relation est lue après fermeture de la session (500 en production, invisible ailleurs) |
| `ruff` (`DTZ`, `T20`, `S`) | `datetime.now()` sans fuseau · `print()` · faille classique (bandit) |
| `mypy` | une erreur de type dans `app/` (0 toléré) |

---

## 6. Commandes

`make help` liste tout. Les principales :

| Commande | Effet |
|---|---|
| `make check` | **ce que la CI vérifie** : lint + types + tests avec seuil de couverture |
| `make test` · `make test-pg` | suite complète sur SQLite (rapide) · sur PostgreSQL local |
| `make fix` | corrige et formate (ruff) |
| `make rev m="…"` · `make migrate` · `make drift` | créer une migration (formatée automatiquement) · l'appliquer · vérifier modèles ⇄ migrations |
| `make docs` | régénère `API_REFERENCE.md` (jamais à la main) |
| `make up` · `make down` | services de développement (PostgreSQL + profils optionnels) |
| `make create-admin` | crée le premier administrateur (aperçu par défaut) |
| `make hooks` · `make hooks-all` | installe les hooks git · les exécute sur tous les fichiers |
| `make audit` | vulnérabilités connues des dépendances |

---

## 7. Qualité, hooks et pipeline

```text
 commit  ─▶  hygiène des fichiers · gitleaks (secrets) · ruff check · ruff format        (< 2 s)
 push    ─▶  une seule tête Alembic · mypy · API_REFERENCE à jour · pytest + couverture ≥ 90 %  (~1 min)
 PR/CI   ─▶  qualité · tests SQLite + PostgreSQL · migrations sur PostgreSQL · image Docker · audit des dépendances
 tag v*  ─▶  vérification · image GHCR · staging (auto) · production (validation humaine)
```

Les hooks ne se contournent jamais (`--no-verify` interdit). Détail : [`docs/RIGUEUR_DU_CODE.md`](docs/RIGUEUR_DU_CODE.md), [`docs/PIPELINES.md`](docs/PIPELINES.md).

---

## 8. Travailler ici : en humain ou avec une IA

Les règles sont **les mêmes** pour une personne et pour un assistant de code : elles sont écrites dans
[`AGENTS.md`](AGENTS.md) (lu automatiquement par la plupart des outils d'IA ; `CLAUDE.md` y renvoie) et
détaillées dans [`docs/TRAVAILLER_AVEC_UNE_IA.md`](docs/TRAVAILLER_AVEC_UNE_IA.md). Une contribution — quelle que soit
son origine — est acceptée si `make check` est vert, si les tests couvrent le comportement *et* ses refus, et si
l'architecture est respectée. Voir aussi [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 9. Documentation

| Document | Contenu |
|---|---|
| [`AGENTS.md`](AGENTS.md) | règles impératives pour tout contributeur, humain ou IA |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | couches, chemin d'une requête, principes de conception |
| [`docs/RIGUEUR_DU_CODE.md`](docs/RIGUEUR_DU_CODE.md) | conventions, ruff, mypy, hooks, définition de « terminé » |
| [`docs/TESTS.md`](docs/TESTS.md) | stratégie de tests, garde-fous, quoi tester pour chaque changement |
| [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md) | Alembic : flux, formatage automatique, revue, opérations dangereuses |
| [`docs/MODULES_REUTILISABLES.md`](docs/MODULES_REUTILISABLES.md) | contrat d'un module, le réutiliser d'un projet à l'autre |
| [`docs/AJOUTER_UN_MODULE.md`](docs/AJOUTER_UN_MODULE.md) | pas à pas : créer une ressource sans rien oublier |
| [`docs/PIPELINES.md`](docs/PIPELINES.md) | CI, déploiement, environnements GitHub, retour arrière |
| [`docs/TRAVAILLER_AVEC_UNE_IA.md`](docs/TRAVAILLER_AVEC_UNE_IA.md) | cadre de travail avec un assistant de code |
| [`docs/SECURITE.md`](docs/SECURITE.md) | modèle de sécurité, mesures, tests, ce qui n'est pas couvert |
| [`docs/ENVIRONNEMENTS.md`](docs/ENVIRONNEMENTS.md) | environnements, verrous de démarrage, variables |
| [`docs/BASES_DE_DONNEES.md`](docs/BASES_DE_DONNEES.md) | PostgreSQL ou MongoDB : choisir, configurer, étendre |
| [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) | e-mail et stockage de fichiers : utilisation et sécurité |
| [`docs/VERSIONNAGE_API.md`](docs/VERSIONNAGE_API.md) | `/api/{version}` : règle globale, passer à `v2`, servir deux versions |
| [`docs/PAGINATION.md`](docs/PAGINATION.md) | contrat de pagination, filtres, tri |
| [`docs/LOGS_ET_ERREURS.md`](docs/LOGS_ET_ERREURS.md) | format d'erreur, codes, logs par environnement, conventions de journalisation |
| [`docs/AUDIT.md`](docs/AUDIT.md) | journal d'audit : garanties et usage |
| [`docs/SCALABILITE.md`](docs/SCALABILITE.md) | workers, pool de connexions, Redis, sondes |
| [`docs/REGLES_ET_LECONS.md`](docs/REGLES_ET_LECONS.md) | les pièges réels qui ont motivé chaque règle |
| [`API_REFERENCE.md`](API_REFERENCE.md) | toutes les routes (généré) |

---

## 10. Créer un projet à partir du template

1. **Créer le dépôt** (GitHub : *Use this template*), cloner, puis suivre [§2](#2-démarrer-en-5-minutes).
2. **Renommer** : `name`/`description` dans `pyproject.toml`, `APP_NAME` dans `.env.example`, noms de bases dans `docker-compose.yml`/`Makefile` si besoin.
3. **Définir vos rôles** : `UserRole` (`app/modules/users/enums.py`) et `ROLE_PERMISSIONS` (`app/core/authz.py`), puis une migration.
4. **Créer vos modules** en copiant `projects` : [`docs/AJOUTER_UN_MODULE.md`](docs/AJOUTER_UN_MODULE.md). Supprimer ensuite `projects` (liste de retrait dans le même document).
5. **Choisir vos services** : `DATABASE_BACKEND`, `EMAIL_BACKEND`, `STORAGE_BACKEND` ; installer les extras utiles (`make install-extras EXTRAS="storage mongo"`).
6. **Protéger la branche principale** et configurer les Environments GitHub : [`docs/PIPELINES.md`](docs/PIPELINES.md).
7. `make check` doit rester vert **à chaque commit**.

---

## 11. Limites assumées

- **MongoDB** : le template fournit la sélection, la connexion, la configuration, la sonde de santé et les verrous ;
  les modules d'exemple (auth, projects, audit) reposent sur SQLModel/Alembic. Avec `mongodb`, vous écrivez vos
  propres modules (guide dans `docs/BASES_DE_DONNEES.md`).
- **Cloudinary / S3** : adaptateurs testés avec des clients simulés ; à valider contre le vrai service dans votre projet.
- **Déploiement** : le workflow `deploy.yaml` construit et publie l'image, mais les étapes de déploiement sont
  **à adapter** à votre hébergement et échouent volontairement tant qu'elles ne le sont pas.
- **Sécurité** : voir « Ce qui n'est PAS couvert » dans [`docs/SECURITE.md`](docs/SECURITE.md).
