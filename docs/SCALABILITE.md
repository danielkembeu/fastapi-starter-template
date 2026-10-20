# Montée en charge : workers, connexions et Redis expliqués simplement

## 1. Un seul « employé » pour tout le monde

Un *worker* est un processus qui traite les requêtes. Avec un seul worker, une requête longue (calcul de mot
de passe bcrypt, envoi d'un fichier, rapport lourd) fait attendre **tous les autres**. Plusieurs workers =
plusieurs vendeurs en parallèle. Le `Dockerfile` en lance `WEB_CONCURRENCY` (2 par défaut) ; règle pratique :
environ **un par cœur réservé à l'API**.

## 2. Chaque worker ouvre ses propres connexions à la base

Chaque worker garde un petit **pool** de connexions PostgreSQL. PostgreSQL n'en accepte qu'un nombre maximal
(`max_connections`, 100 par défaut). Elles se **multiplient** :

```text
connexions maximales de l'API  =  workers  ×  (DB_POOL_SIZE + DB_MAX_OVERFLOW)
```

| Exemple | Calcul | Résultat |
|---|---|---|
| 4 workers, pool 10 + 5 de débordement | 4 × 15 | **60** connexions au pire |
| `max_connections` | | 100 |
| Marge | 100 − 60 | 40 (migrations, `psql` manuel, sauvegardes) ✅ |

Si ce produit dépasse `max_connections`, les requêtes échouent **quand le trafic est le plus fort**.
**Règle : le produit doit rester sous `max_connections`, avec de la marge.**

## 3. Pourquoi Redis (le compteur partagé)

- **`memory://` (défaut)** : chaque worker a *son propre* compteur. Avec 4 workers, « 5 tentatives par minute »
  devient jusqu'à 20. Acceptable en développement, **pas en production**.
- **`redis://…`** : un seul compteur partagé → la limite est exacte.

L'application utilise Redis dès que `RATE_LIMIT_STORAGE_URI` commence par `redis` ; `/health/ready` le vérifie alors.
Si Redis tombe, la limitation est suspendue (**fail-open**) au lieu de couper l'API.

## 4. Écrire du code qui passe à l'échelle

| À éviter | À faire |
|---|---|
| Renvoyer toute une table | toujours paginer (`docs/PAGINATION.md`) |
| Compter en Python après avoir chargé les lignes | agrégations SQL (`COUNT`, `SUM`, `GROUP BY`) |
| Une requête par élément d'une liste (N+1) | jointure ou `eager(...)` (`app/core/sql.py`) |
| Lire puis écrire pour attribuer une ressource | `UPDATE … WHERE état = attendu`, vérifier `rowcount` |
| Plusieurs transactions pour une opération | une seule, un seul `commit()` |
| Filtrer/trier sur une colonne sans index | index dans la migration |

## 5. Dimensionnement de départ (exemple : 6 vCPU / 12 Go)

| Composant | Réglage | Pourquoi |
|---|---|---|
| API | `WEB_CONCURRENCY=4` | ~1 worker par cœur, 2 cœurs laissés à PostgreSQL / Redis / système |
| API | `DB_POOL_SIZE=10`, `DB_MAX_OVERFLOW=5` | 4 × 15 = 60 connexions au pire |
| PostgreSQL | `max_connections=100`, `shared_buffers≈25 % RAM`, `work_mem=16MB` | `work_mem` est multiplié par tri et par connexion : rester prudent |
| Redis | `maxmemory 1gb`, `allkeys-lru` | cache : s'évince tout seul |

Points de départ à **mesurer** (Sentry, `/health/ready`, logs) avant d'ajuster.

## 6. Sondes de santé

| Route | Question | Teste | Si elle échoue |
|---|---|---|---|
| `/health/live` | le processus répond ? | **rien d'autre** | l'orchestrateur redémarre le conteneur |
| `/health/startup` | le démarrage est fini ? | drapeau interne | on attend |
| `/health/ready` | peut-on servir du trafic ? | base, Redis (si utilisé), **révision Alembic = tête** | on retire l'API de la rotation, **sans** redémarrer |

`live` ne teste pas la base : sinon un hoquet de 5 s ferait échouer la sonde de **tous** les conteneurs, qui
redémarreraient ensemble et se reconnecteraient tous à une base déjà en difficulté — un incident mineur
deviendrait une panne totale. `ready` compare la révision Alembic de la base à celle du code déployé : une
migration oubliée rend l'API **non prête** au lieu de servir contre un schéma qu'elle ne comprend pas.
