# Rigueur du code

La rigueur n'est pas une affaire de goût ou de vigilance : c'est un **ensemble de contrôles automatiques** que
chaque contribution traverse, dans le même ordre, en local et en CI. Ce qui passe chez vous passe en CI.

## Les quatre filtres

| Filtre | Quand | Durée | Bloque |
|---|---|---|---|
| **Éditeur / `make fix`** | en écrivant | instantané | rien (corrige) |
| **Hooks de commit** | `git commit` | < 2 s | un secret, un fichier cassé, un style non conforme |
| **Hooks de push** | `git push` | ~1 min | une tête Alembic multiple, une erreur de type, une API non documentée, un test rouge, une couverture < 90 % |
| **CI** | PR / push | quelques minutes | tout ce qui précède, plus PostgreSQL réel, migrations, image Docker |

> Un contrôle présent seulement en CI est découvert trop tard ; un contrôle présent seulement dans l'éditeur
> n'existe pas. Chaque règle importante est donc vérifiée **au moins par un test ou un hook**.

## Hooks (`.pre-commit-config.yaml`)

```bash
source env/bin/activate     # indispensable : les hooks lancent `python -m ruff` du venv
make hooks                  # installe commit + push
make hooks-all              # exécute tout sur tous les fichiers
```

| Étape | Hook | Protège contre |
|---|---|---|
| commit | `end-of-file-fixer`, `trailing-whitespace`, `mixed-line-ending` | diffs parasites |
| commit | `check-yaml/toml/json`, `check-merge-conflict`, `check-case-conflict` | fichiers cassés |
| commit | `detect-private-key`, **`gitleaks`** | clé ou secret committé |
| commit | `debug-statements` | `breakpoint()` oublié |
| commit | **`ruff check`**, **`ruff format --check`** | style, bugs classiques, failles |
| push | **`alembic-single-head`** | deux migrations parallèles |
| push | **`mypy`** | erreurs de types |
| push | **`api-reference`** | `API_REFERENCE.md` périmé |
| push | **`pytest` + couverture** | régression, couverture qui s'érode |

**Règles sur les hooks** : jamais `--no-verify`. Un hook qui échoue dit la vérité : corriger la cause. Si un hook
modifie des fichiers (formatage), les ajouter (`git add -u`) et recommencer le commit.

Pannes fréquentes : `No module named ruff` ⇒ venv non activé. `gitleaks` signale une fausse valeur de test ⇒
ajouter `# gitleaks:allow (valeur factice de test)` sur la ligne (jamais affaiblir le hook).

## Ruff (lint + format)

Configuré dans `pyproject.toml` (largeur 100). Familles actives et ce qu'elles protègent :

| Famille | Protège contre |
|---|---|
| `F`, `E`, `W` | noms indéfinis, imports inutilisés, erreurs de syntaxe |
| `I` | ordre des imports (diffs stables) |
| `B`, `SIM`, `C4`, `UP`, `RUF` | pièges classiques, code verbeux, syntaxe obsolète |
| **`DTZ`** | `datetime.now()` sans fuseau → utiliser `app.core.clock.utc_now()` |
| **`T20`** | `print()` de débogage oublié → utiliser `logging` |
| **`S`** (bandit) | secrets en dur, SQL construit, `subprocess`, `assert` en production |
| `PT`, `ASYNC` | style pytest, appels bloquants dans du code async |

`# noqa` n'est admis qu'avec **le code de la règle et la raison** sur la même ligne :
`# noqa: S104 — dans un conteneur, écouter sur toutes les interfaces est voulu`.

## Mypy (types)

`make type` : **0 erreur toléré**, bloquant en hook de push et en CI. `app/core/` (le socle réutilisable) est
vérifié plus strictement : toute fonction y est entièrement annotée.

Idiomes SQLModel à connaître :

```python
select(User).where(col(User.email).ilike(pattern, escape="\\"))   # col() pour les colonnes dans ilike/in_/update/delete
session.exec(select(Project).options(*eager(Project.owner)))      # eager() (app/core/sql.py) pour selectinload
settings = Settings()  # type: ignore[call-arg]                    # un type: ignore reste SUR sa ligne
```

Ne pas « réparer » mypy avec `Any` ou `# type: ignore` sans justification : un type qui résiste révèle souvent un vrai bug.

## Conventions

| Sujet | Règle |
|---|---|
| Langues | commentaires, docstrings et messages d'erreur en **français** ; identifiants en **anglais** |
| Nommage | `snake_case` fonctions/variables, `PascalCase` classes, `UPPER_CASE` constantes ; tests `test_<comportement_attendu>` en phrase |
| Docstrings | une phrase qui dit **ce que la fonction garantit** (et le *pourquoi* si ce n'est pas évident) ; pas de paraphrase du code |
| Commentaires | expliquent le *pourquoi* (contrainte, piège évité), jamais le *quoi* ; pas de code commenté |
| Erreurs | `HTTPException` avec un message clair ; codes : `400` entrée/règle, `401`, `403`, `404`, `409` conflit d'état, `429` |
| Horloge | `utc_now()` partout ; colonnes `TIMESTAMP` en UTC naïf |
| Argent / exactitude | choisir une représentation (entiers, `Decimal`) et la documenter avant le premier montant |
| Dépendances | épinglées (`==`) dans `requirements*.txt` ; mises à jour par Dependabot, validées par la CI |
| Taille | une fonction qui ne tient plus sur un écran, un service qui dépasse ~400 lignes : découper |

## Définition de « terminé »

- [ ] `make check` vert (lint + types + tests + couverture)
- [ ] Tests : cas nominal **et** refus (403), isolation, entrées invalides, conflits d'état
- [ ] Garde-fous à jour : matrice d'accès, décisions d'audit, contrat OpenAPI
- [ ] `.env.example` et `API_REFERENCE.md` à jour (`make docs`)
- [ ] Migration relue, rejouable, sans dérive (`make drift`) — si le schéma change
- [ ] Documentation modifiée là où le comportement a changé
- [ ] **Vérifié pour de vrai** : le test a été exécuté et sa sortie lue ; la règle cassée volontairement fait bien échouer le test

## Dette technique : la traiter, pas la cacher

Un assouplissement temporaire (`continue-on-error`, seuil de couverture abaissé, `# type: ignore`) doit porter un
commentaire **« à lever quand … »** et être listé dans la PR. Un seuil de couverture ne s'abaisse jamais pour faire passer
un changement : on ajoute les tests.
