# Environnements et configuration

## Pourquoi des environnements

Une application qui ne sait pas où elle tourne finit par écrire dans la mauvaise base. L'application connaît son
environnement (`ENVIRONMENT`) et **refuse de démarrer** si la configuration est dangereuse pour lui.

## Les quatre environnements

| `ENVIRONMENT` | Usage | Base de données | `/docs`, `/redoc` | Logs |
|---|---|---|---|---|
| `local` | poste du développeur | **locale uniquement** (`make up`) | ouvert | lisibles, DEBUG |
| `ci` | tests automatiques | éphémère (SQLite ou PostgreSQL de test) | ouvert | lisibles, INFO |
| `staging` | pré-production | copie anonymisée | **HTTP Basic** | JSON, INFO |
| `production` | les vrais utilisateurs | réelle, sauvegardée | **inexistant** (404) | JSON, INFO |

« JSON » = une ligne JSON par événement (`ts`, `level`, `logger`, `message`, `request_id`, `exception`). `LOG_LEVEL`
force un niveau quel que soit l'environnement.

## D'où vient la configuration (priorité décroissante)

1. **Variables d'environnement réelles** (Docker, GitHub Actions…) — elles gagnent toujours ;
2. un fichier `.env.<ENVIRONMENT>` (`.env.local`…) — **confort de développement uniquement** ;
3. les valeurs par défaut de la classe `Settings` (`app/core/config.py`).

En `ci`, `staging` et `production`, **aucun fichier de secrets** n'est déposé sur un serveur ni dans une image.

## Les verrous de démarrage

Si l'un d'eux échoue, l'application s'arrête en listant **tous** les problèmes d'un coup.

**Dans tous les environnements** — paramètres exigés par le backend choisi :

| Backend choisi | Variables requises |
|---|---|
| `DATABASE_BACKEND=postgres` | `DATABASE_URL` |
| `DATABASE_BACKEND=mongodb` | `MONGODB_URL`, `MONGODB_DB_NAME` |
| `EMAIL_BACKEND=smtp` | `SMTP_HOST`, `EMAIL_FROM` ; `SMTP_USE_TLS` et `SMTP_USE_SSL` exclusifs |
| `STORAGE_BACKEND=cloudinary` | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` |
| `STORAGE_BACKEND=s3` | `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` |

**Selon l'environnement** :

| Environnement | Refus si… |
|---|---|
| `local` | l'URL de la base (PostgreSQL ou MongoDB) pointe vers une base **distante** (sauf `ALLOW_REMOTE_DB_IN_LOCAL=true`) |
| tous | `LOG_LEVEL` inconnu · `API_VERSION` mal formée |
| `production` | `ERROR_DEBUG=true` (le détail technique ne doit jamais atteindre le client) |
| `staging`, `production` | `SECRET_JWT` < 32 caractères ou secret de développement connu |
| | l'URL de la base est SQLite ou locale |
| | `CORS_ORIGINS` vide ou contenant `*` ; en production, une origine `localhost` |
| | `EMAIL_BACKEND=console` (n'enverrait rien) — choisir `smtp` ou `disabled` |
| | `STORAGE_BACKEND=local` (disque éphémère) — choisir `cloudinary`, `s3` ou `disabled` |
| `staging` | `DOCS_USERNAME` / `DOCS_PASSWORD` absents |

**Pour ajouter un verrou** : `Settings._backend_problems` (tous environnements) ou `_exposure_problems` (exposés) dans
`app/core/config.py`, et un test dans `tests/core/test_config.py`.

## Variables

`.env.example` documente **toutes** les variables, groupées (application, base de données, authentification, réseau,
Redis et débit, e-mail, stockage, supervision, services de développement). Le test `test_env_example.py` garantit
qu'il reste synchrone avec `Settings`. Les variables lues hors de `Settings` : `WEB_CONCURRENCY` et
`FORWARDED_ALLOW_IPS` (Dockerfile), `POSTGRES_*`, `*_PORT` (docker-compose).

Ports de développement (publiés sur `127.0.0.1` par `make up`, modifiables) : PostgreSQL `55432`, Redis `56379`,
MongoDB `57017`, SMTP de développement `51025` (interface `58025`), MinIO `59000` (console `59001`). Ils sont volontairement
hors des ports usuels pour ne pas entrer en conflit avec des services déjà installés.

## Développer en local

```bash
make up                       # PostgreSQL local (+ make up PROFILES="cache mongo mail storage" pour le reste)
cp .env.example .env.local    # renseigner SECRET_JWT
make migrate && make dev
```

> `make migrate` et `make dev` agissent sur la base de `.env.local`. **Vérifiez qu'elle est locale** : l'application
> refusera de démarrer sinon (c'est voulu). Avant toute commande qui écrit en base (script, `alembic`…), fixez la cible
> explicitement ; ne lancez jamais un script destructif « pour voir ».

## Ajouter une variable

1. La typer dans `Settings` avec un **défaut sûr**.
2. La documenter dans `.env.example` (le test échoue sinon).
3. Si son oubli est dangereux, ajouter un verrou et son test.
4. Si elle est propre à un environnement, la déclarer dans l'Environment GitHub correspondant (`docs/PIPELINES.md`).
