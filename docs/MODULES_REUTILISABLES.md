# Modules réutilisables

Un module bien fait se **déplace d'un projet à l'autre**. Cette page définit ce qu'est un module réutilisable, les
règles de dépendance qui le permettent, et comment le réutiliser sans le dupliquer n'importe comment.

## Le contrat d'un module

Un module est un dossier `app/modules/<nom>/` qui contient **tout** ce qui le concerne :

```text
app/modules/<nom>/
 ├ models.py      tables
 ├ enums.py       états
 ├ schemas.py     entrées / sorties / filtres
 ├ service.py     logique métier — la seule couche qui décide
 └ router.py      routes + permissions, rien d'autre
tests/<nom>/      ses tests, qui voyagent avec lui
```

Et il ne dépend que de :

| Peut dépendre de | Ne doit **pas** dépendre de |
|---|---|
| `app/core/*` (configuration, autorisation, pagination, audit, horloge, e-mail, stockage…) | un **autre module métier** (sauf via une interface explicite, voir plus bas) |
| `app/modules/users` (le modèle `User`) et `app/modules/audit` (le service d'audit) | `app/server.py`, des variables d'environnement lues directement |
| la bibliothèque standard et les dépendances déclarées | un détail interne d'un autre module (`from app.modules.x.service import _privé`) |

**Pourquoi** : tant que les dépendances vont *vers le bas* (module → core), on peut retirer, ajouter ou copier un
module sans rien casser. Une dépendance module → module crée un cycle ou un couplage qu'on paie plus tard.

## Règles pour qu'il reste réutilisable

1. **Aucune valeur propre au projet en dur.** Ce qui varie (limites, délais, URL, noms) vit dans `Settings`, avec un défaut sûr, et dans `.env.example`.
2. **Les permissions sont déclarées dans `authz.py`**, pas dans le module : le module *demande* une permission, le projet décide quel rôle la reçoit.
3. **Pas de rôle codé en dur.** Jamais `if user.role == …`. Utiliser `can()`, `ensure_owner_or_permission`, `Requires*`.
4. **L'audit passe par `AuditService`**, avec des actions du catalogue `AuditAction` (à étendre dans le projet d'accueil).
5. **Les effets externes passent par `app/core/email.py` et `app/core/storage.py`**, pas par un SDK appelé directement : changer de fournisseur ne touche pas le module.
6. **Les tests voyagent avec le module** et n'utilisent que les fixtures standard (`client`, `session`, `users`, `rate_limit`).
7. **Les garde-fous restent exhaustifs** : un module copié doit apparaître dans la matrice d'accès, les décisions d'audit, le contrat OpenAPI.

## Dépendre d'un autre module : par une interface

Si le module B a vraiment besoin du module A (ex. les tâches ont besoin des projets) :

- **Appeler le `service` de A** (jamais ses modèles ou son router) et **ne lire que son API publique** (méthodes sans `_`).
- Ou définir dans B un `Protocol` minimal décrivant ce dont il a besoin ; A l'implémente. B reste testable avec un faux.
- Une dépendance dans l'autre sens est un cycle : la résoudre en déplaçant le point commun dans `core/` ou dans un troisième module.
- Documenter la dépendance en tête du `service.py` de B.

## Réutiliser un module dans un autre projet

### Option 1 — copie contrôlée (par défaut, recommandée au début)

1. Copier `app/modules/<nom>/` et `tests/<nom>/` dans le projet cible.
2. Brancher : import du modèle dans `app/modules/__init__.py`, `include_router` dans `app/server.py`.
3. Déclarer les **permissions** dans `authz.py` et les attribuer aux rôles du projet.
4. Ajouter les **actions d'audit** et le type de ressource.
5. Générer la **migration** (`make rev`), la relire.
6. Mettre à jour les **garde-fous** : matrice d'accès, décisions d'audit, contrat OpenAPI, cycle de session.
7. `make check`. Tout ce qui est rouge dit ce qui manque.

La copie est simple et sans magie, mais deux copies divergent. **Noter dans le module d'où il vient** (projet, version)
dans un en-tête de `service.py`, pour pouvoir reporter une correction.

### Option 2 — paquet interne (quand un module est stable et utilisé par 3 projets ou plus)

Extraire le module dans un dépôt/paquet versionné (`pip install git+https://…@v1.2.0`), avec :
- une version sémantique et un `CHANGELOG` ;
- ses propres tests et sa propre CI ;
- une **API publique** documentée (ce qui est exporté) ;
- les migrations livrées avec le paquet, ou un modèle abstrait que chaque projet matérialise.

Ne passer à cette option que lorsque la duplication coûte plus que la gestion du paquet.

## Candidats naturels à la réutilisation

| Module | Ce qu'il apporte | Dépend de |
|---|---|---|
| `audit` | journal en ajout seul, service, consultation | `core` |
| `auth` + `users` | comptes, sessions, jetons, verrouillage | `core`, `audit` |
| *(à créer)* `notifications` | notifications internes + e-mail | `core.email`, `users` |
| *(à créer)* `files` | téléversements validés, URL | `core.storage` |
| *(à créer)* `password_resets` | réinitialisation (par e-mail ou validation d'un admin) | `auth`, `core.email` |

## Anti-patrons

| À éviter | À faire |
|---|---|
| Copier-coller une fonction d'un module à l'autre | la remonter dans `core/` |
| Lire `os.environ` dans un module | ajouter une variable à `Settings` |
| `from app.modules.projects.models import Project` dans `tasks` | passer par le service ou une interface |
| Un module qui connaît le nom d'un rôle | demander une permission |
| Ajouter un champ « spécial client » dans un module partagé | l'étendre dans le projet, ou prévoir un point d'extension |
