# Travailler avec un assistant de code

Ce dépôt est conçu pour qu'un assistant de code (Claude Code, Copilot, Cursor…) y produise du travail **aussi sûr que
celui d'un humain attentif** — non parce qu'on lui fait confiance, mais parce que **les contrôles sont automatiques**
et s'appliquent à l'identique à tous.

> **Principe** : une IA est rapide et sûre d'elle, y compris quand elle se trompe. Le cadre ne vise donc pas à
> *l'empêcher d'écrire*, mais à **rendre toute erreur visible tout de suite** : tests qui peuvent échouer, garde-fous
> structurels, hooks, CI. Un changement est accepté sur ses **preuves**, jamais sur l'assurance de son auteur.

## Ce que l'IA doit lire (dans cet ordre)

1. **[`AGENTS.md`](AGENTS.md)** — règles impératives, lues automatiquement par la plupart des outils (`CLAUDE.md` y renvoie).
2. `README.md` puis `docs/ARCHITECTURE.md`.
3. Selon la tâche : `docs/AJOUTER_UN_MODULE.md`, `docs/MIGRATIONS.md`, `docs/TESTS.md`, `docs/SECURITE.md`.
4. Le **module d'exemple** `app/modules/projects/` et ses tests : c'est le modèle de style, de structure et de rigueur.

## Comment formuler une demande

Une bonne demande contient : le **résultat attendu**, le **périmètre** (quels modules), les **contraintes** (sécurité,
compatibilité) et le **critère de réussite** vérifiable.

| Mauvais | Bon |
|---|---|
| « Ajoute les tâches » | « Ajoute le module `tasks` sur le modèle de `projects` : un utilisateur crée et clôture ses tâches, un admin les lit toutes. Statuts `todo → doing → done`. Suivre `docs/AJOUTER_UN_MODULE.md`. `make check` doit être vert. » |
| « Corrige le bug de connexion » | « Un compte bloqué garde l'accès tant que son jeton est valide. Écris d'abord le test qui échoue, puis corrige. » |
| « Ajoute du cache » | « Propose d'abord une approche et ses compromis ; n'implémente pas avant mon accord. » |

## Les rails qui s'appliquent à l'IA

| Rail | Effet sur l'IA |
|---|---|
| **Tests qui peuvent échouer** | un code faux fait rougir un test ; l'IA doit lire la sortie, pas supposer |
| **Garde-fous structurels** (matrice d'accès, audit, contrat OpenAPI, migrations, `.env.example`) | si l'IA oublie de protéger, tracer, paginer ou migrer, la suite échoue **en nommant ce qui manque** |
| **Hooks de commit/push** | secrets, lint, types, tests bloquent avant même la PR |
| **Verrous de démarrage** | une configuration dangereuse empêche le démarrage au lieu de passer inaperçue |
| **CI + branche protégée** | rien n'atteint `main` sans PR verte |
| **Aperçu par défaut des scripts d'écriture** | une commande de données montre sa cible avant d'agir |

## Comportements attendus de l'IA

- **Chercher avant d'écrire** : utiliser l'existant (`app/core`, `projects`), ne pas réinventer.
- **Faire petit et vérifiable** : un sujet par changement ; lancer `make check` ; lire la sortie.
- **Montrer les preuves** : « tous les tests passent, mypy 0 erreur » **avec la sortie des commandes**, pas « ça devrait marcher ».
- **Écrire le test d'abord pour un bug**, et vérifier qu'il échoue pour la bonne raison.
- **Casser volontairement la règle** pour prouver que le test la protège, puis restaurer.
- **Dire ce qui est incertain** et ce qui n'a pas été vérifié, plutôt que deviner ou masquer.
- **Rapporter fidèlement** : un test rouge se signale avec sa sortie ; une étape sautée se déclare.
- **Demander avant l'irréversible** : suppression, migration sur une base partagée, publication, envoi d'e-mails réels.

## Ce que l'IA ne doit jamais faire

| Interdit | Pourquoi |
|---|---|
| Désactiver, assouplir ou supprimer un test, un hook, un verrou ou une règle ruff pour « faire passer » | on corrige la cause ; si la règle est fausse, on le dit et on demande |
| `--no-verify`, `# type: ignore`/`# noqa` sans justification, abaisser `COV_MIN` | contourne exactement ce qui nous protège |
| Écrire en base sans avoir vérifié la cible, lancer un script destructif « pour voir » | une base de production ne se récupère pas d'un test d'essai |
| Coller un secret, une URL de base réelle ou des données personnelles dans le code, un test, un commit ou un message | les secrets restent dans l'environnement |
| Modifier une migration déjà poussée | d'autres bases l'ont appliquée |
| Éditer `API_REFERENCE.md` à la main | il est généré et vérifié |
| Introduire du code « au cas où », des abstractions inutiles, des fonctionnalités non demandées | chaque ligne est une surface d'erreur à tester et à maintenir |
| Annoncer « terminé » sans avoir exécuté la vérification | la confiance se fonde sur des preuves |

## Revoir un changement produit par une IA

La revue ne relit pas tout ligne à ligne : elle vérifie les **points où une IA se trompe**.

- [ ] Les tests couvrent-ils les **refus** (403, 404 d'autrui, 400, 409), pas seulement le cas heureux ?
- [ ] Un test **peut-il échouer** ? (casser la règle et observer)
- [ ] Chaque route a-t-elle sa permission, sa décision d'audit, sa pagination ?
- [ ] La logique est-elle dans le **service** (pas dans le router) ?
- [ ] Les montants/états/propriétaires sont-ils décidés **côté serveur** ?
- [ ] Une **migration** est-elle nécessaire, relue, rejouable ?
- [ ] Aucun secret, `print`, `datetime.now()`, contournement ou assouplissement n'a été introduit ?
- [ ] Le changement fait-il **exactement** ce qui était demandé — ni plus, ni moins ?

## Un assistant ou plusieurs

Plusieurs assistants (ou personnes) peuvent travailler en parallèle **sur des modules différents**, sur des branches
séparées : le contrat de module (`docs/MODULES_REUTILISABLES.md`) limite les conflits. Les fichiers partagés — `authz.py`,
`audit/enums.py`, `app/modules/__init__.py`, `app/server.py`, les tables des garde-fous — sont les seuls points de
fusion : les modifier par petits ajouts, et relancer `make check` après chaque fusion.

## Adapter `AGENTS.md` à votre projet

Le fichier est un point de départ. Ajouter, au fil du projet, **les règles apprises à la dure** (« toujours X parce
que Y nous a coûté Z »), avec le *pourquoi*. Une règle sans raison est ignorée ; une règle vérifiée par un test ou un
hook est appliquée.
