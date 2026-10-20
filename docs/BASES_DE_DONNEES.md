# Bases de données : PostgreSQL ou MongoDB

Le choix se fait par **une variable** : `DATABASE_BACKEND=postgres` (défaut) ou `mongodb`. Les paramètres du backend
choisi sont exigés au démarrage ; ceux de l'autre sont ignorés.

## Choisir

| Besoin | Choix |
|---|---|
| Données relationnelles, transactions, intégrité (comptes, transactions financières, stocks), requêtes d'agrégation | **PostgreSQL** |
| Documents à structure variable, très peu de relations, évolution rapide du schéma | MongoDB |
| Les deux (ex. données métier en PostgreSQL, événements/journaux en MongoDB) | voir « Les deux » plus bas |

En cas de doute : **PostgreSQL**. C'est le backend de référence du template, avec migrations, audit en ajout seul
et tous les modules fournis.

## PostgreSQL (`DATABASE_BACKEND=postgres`)

```dotenv
DATABASE_BACKEND=postgres
DATABASE_URL=postgresql://utilisateur:motdepasse@hote:5432/base
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5
```

- Couche : `app/core/database.py` (`DBSessionDep`, `engine`), modèles SQLModel, migrations Alembic.
- Développement : `make up` (PostgreSQL 16, bases `app_dev` et `app_test`).
- Verrous : en local, une base **distante** est refusée (`ALLOW_REMOTE_DB_IN_LOCAL=true` pour passer outre sciemment) ;
  en staging/production, une base locale ou SQLite est refusée.
- Taille du pool : `WEB_CONCURRENCY × (DB_POOL_SIZE + DB_MAX_OVERFLOW)` doit rester sous `max_connections` (`docs/SCALABILITE.md`).

## MongoDB (`DATABASE_BACKEND=mongodb`)

```dotenv
DATABASE_BACKEND=mongodb
MONGODB_URL=mongodb://utilisateur:motdepasse@hote:27017
MONGODB_DB_NAME=app
MONGODB_TIMEOUT_MS=2000
```

```bash
make install-extras EXTRAS="mongo"      # pymongo (dépendance optionnelle, import paresseux)
make up PROFILES="mongo"                # MongoDB local sur 127.0.0.1:57017
```

Ce que le template fournit pour MongoDB :

| Élément | Où |
|---|---|
| sélection et validation de la configuration (URL et nom de base requis, base locale refusée en production, base distante refusée en local) | `app/core/config.py` |
| client unique par processus, dépendance FastAPI `MongoDBDep`, `ping()` | `app/core/mongo.py` |
| sonde `/health/ready` qui interroge MongoDB (au lieu de PostgreSQL) | `app/core/health.py` |
| tests de tout ce qui précède | `tests/core/test_mongo.py`, `test_config.py`, `test_health.py`, `test_backend_selection.py` |

> **Limite à connaître** : les modules fournis (`auth`, `projects`, `audit`) reposent sur **SQLModel et Alembic**. Avec
> `mongodb`, `app/server.py` ne les monte pas (il journalise un avertissement) : l'application expose uniquement les sondes
> de santé, et **vous écrivez vos propres modules MongoDB**. L'authentification, l'autorisation (RBAC), l'audit et la pagination
> sont à réimplémenter sur Mongo pour ces modules — le noyau (`authz`, `pagination`, `security`, `errors`) reste réutilisable.

### Écrire un module MongoDB

```python
# app/modules/notes/service.py
from fastapi import HTTPException
from pymongo.database import Database
from app.core.clock import utc_now

class NoteService:
    @staticmethod
    def create(db: Database, owner_id: str, text: str) -> dict:
        document = {"owner_id": owner_id, "text": text, "created_at": utc_now()}
        db.notes.insert_one(document)
        return document
```

```python
# app/modules/notes/router.py
@router.post("", status_code=201)
def create_note(payload: NoteCreate, db: MongoDBDep, user: ...):
    return NoteService.create(db, str(user.id), payload.text)
```

Règles identiques à PostgreSQL : logique dans le service, permission déclarée, **propriétaire décidé côté serveur**,
validation des entrées par Pydantic, **tests avec un faux client** (aucun appel réseau), `404` pour la ressource d'autrui.
Spécificités MongoDB : créer les **index** explicitement (au démarrage ou par un script versionné), valider les
`ObjectId` avant requête, ne jamais passer d'entrée utilisateur brute comme filtre (injection d'opérateurs `$where`, `$ne`),
et décider une stratégie de « migration » des documents (version de schéma dans le document).

Pour activer vos routers sous MongoDB, les monter dans la branche `else` de `app/server.py`.

## Les deux

Pour de la donnée relationnelle **et** documentaire, garder `DATABASE_BACKEND=postgres` pour le noyau (comptes, audit) et
utiliser `app/core/mongo.py` pour un module précis : définir `MONGODB_URL`/`MONGODB_DB_NAME` et appeler `get_mongo_db()`.
Attention : la configuration actuelle n'exige les paramètres MongoDB que si `mongodb` est le backend choisi, et la sonde de
santé ne vérifie que le backend choisi. Ajoutez la vérification de MongoDB à `/health/ready` si votre projet en dépend.

## Changer de backend en cours de projet

Peu coûteux au début (configuration), très coûteux ensuite (modèles, requêtes, tests, migration des données). Choisir
**avant** d'écrire le premier module métier.
