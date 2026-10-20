# Migrations (Alembic)

> **Alembic est le seul maître du schéma.** L'application ne crée jamais de tables au démarrage. Une base dont le
> schéma ne correspond pas au code déployé est détectée (`/health/ready` devient `503`) et bloque la mise en service.

## Le flux

```bash
# 1. modifier le modèle (app/modules/<m>/models.py), l'importer dans app/modules/__init__.py si nouveau
make rev m="ajout budget des projets"     # 2. génère la migration (formatée automatiquement)
# 3. RELIRE le fichier généré — l'autogénération ne comprend ni vos intentions ni vos données
make migrate                              # 4. l'applique sur la base locale
make drift                                # 5. doit ne rien signaler (modèles = migrations)
make test-pg                              # 6. valide sur PostgreSQL réel
alembic downgrade -1 && alembic upgrade head    # 7. vérifie que le retour arrière ET le rejeu fonctionnent
```

## Formatage automatique

`alembic.ini` définit des **hooks post-écriture** : chaque migration générée est passée à `ruff check --fix` puis
`ruff format`, comme le reste du code. Aucun diff de style ne pollue les revues, et le hook de commit ne bloque
pas sur un fichier généré. Les migrations sont **lintées et formatées comme le code** (elles ne sont pas exclues de ruff).

Nom des fichiers : `AAAAMMJJ_HHMM_<rev>_<slug>.py` — l'ordre alphabétique du dossier suit l'ordre chronologique.

Le gabarit (`alembic/script.py.mako`) importe `sqlmodel` (les colonnes texte générées utilisent
`sqlmodel.sql.sqltypes.AutoString`) et documente la règle du `downgrade`.

## Règles

| Règle | Pourquoi |
|---|---|
| **Une seule tête** (`make heads`) | deux migrations parallèles = ordre ambigu ; hook de push + CI. Fusionner avec `alembic merge` |
| **Ne jamais modifier une migration déjà poussée** | d'autres bases l'ont peut-être appliquée ; en créer une nouvelle |
| **Relire chaque migration générée** | l'autogénération rate les renommages (vus comme suppression + création), les données, les contraintes nommées |
| **`downgrade()` fonctionnel et rejouable** | `drop_table` laisse les types enum PostgreSQL : les supprimer (`sa.Enum(name="…").drop(op.get_bind(), checkfirst=True)`) sinon `upgrade` échoue au rejeu |
| **Pas de `pass` dans `downgrade`** | test `test_every_migration_has_a_downgrade` |
| **Pas de dérive** (`alembic check`) | un modèle modifié sans migration fait échouer le test et la CI |
| **Une migration = un changement logique** | revue et retour arrière plus simples |
| **Index sur les colonnes filtrées/triées** | une liste paginée non indexée devient lente avec les données |
| **Jamais d'import de code applicatif métier dans une migration** | le code évolue, la migration doit rester figée dans le temps |

## Opérations dangereuses

### Colonne obligatoire sur une table existante

`op.add_column(..., nullable=False)` **échoue sur PostgreSQL** si la table contient des lignes. Procédure sûre :

```python
op.add_column("projects", sa.Column("budget", sa.Integer(), nullable=True))
op.execute("UPDATE projects SET budget = 0 WHERE budget IS NULL")   # remplissage
op.alter_column("projects", "budget", nullable=False)
```

ou `server_default="0"`. L'autogénération produit la forme dangereuse : toujours corriger.

### Renommer une colonne ou une table

L'autogénération génère « supprimer + créer » (**perte de données**). Écrire `op.alter_column(..., new_column_name=…)`
ou `op.rename_table(...)` à la main.

### Types enum PostgreSQL

Ajouter une valeur : `ALTER TYPE … ADD VALUE` (ne s'exécute pas dans une transaction sur les anciennes versions ;
prévoir `op.get_context().autocommit_block()`). Retirer une valeur est délicat : créer un nouveau type et migrer.

### Gros volumes et verrous

Une migration qui réécrit une grande table verrouille les écritures. Créer les index avec
`postgresql_concurrently=True` (hors transaction), faire les remplissages par lots, planifier une fenêtre de maintenance si besoin.

### Migrations de données

Les écrire en SQL brut (`op.execute`) ou avec des tables légères définies **dans la migration**, jamais avec les
modèles de l'application. Prévoir leur `downgrade`, ou documenter qu'elles ne sont pas réversibles.

## Déployer une migration

L'ordre est toujours : **sauvegarde → migration → nouvelle version → vérification**.

1. La migration doit être **compatible avec l'ancienne ET la nouvelle version du code** (le temps du déploiement, les deux tournent). Éviter de supprimer ou renommer une colonne en une seule étape : *ajouter* → *déployer le code qui utilise la nouvelle colonne* → *supprimer l'ancienne* dans une release ultérieure.
2. Appliquer `alembic upgrade head` sur la base cible **avant** de démarrer la nouvelle image (voir `docs/PIPELINES.md`).
3. `GET /health/ready` doit répondre `200` : la sonde compare la révision de la base à la tête du code.
4. En cas de problème : revenir à l'image précédente. Si la migration est réversible et qu'aucune donnée écrite par le nouveau code n'est perdue, `alembic downgrade -1` ; sinon restaurer la sauvegarde.

## Dépannage

| Symptôme | Cause / remède |
|---|---|
| `Multiple head revisions` | deux branches de migration : `alembic merge heads -m "fusion"` |
| `type "x" already exists` au rejeu | `downgrade` n'a pas supprimé le type enum |
| `column … contains null values` | colonne obligatoire ajoutée sans valeur (voir plus haut) |
| `Target database is not up to date` | exécuter `make migrate` avant `make rev` |
| `make drift` signale une différence | modèle modifié sans migration, ou migration éditée a posteriori |
| Hook de commit échoue sur une migration | le formatage n'a pas tourné : `ruff format alembic && ruff check --fix alembic` |
| `No module named ruff` pendant `make rev` | venv non activé (le hook utilise `python -m ruff`) |
