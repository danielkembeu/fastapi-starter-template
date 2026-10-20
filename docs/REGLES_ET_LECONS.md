# Règles d'ingénierie et pièges qui les ont motivées

Chaque règle de ce socle existe parce qu'un problème réel l'a rendue nécessaire. Les connaître évite de les
défaire par commodité.

## Configuration et environnements

| Règle | Le piège évité |
|---|---|
| Un environnement explicite et des **verrous de démarrage** | un poste de développement qui écrit dans la base de production parce que deux fichiers `.env` étaient identiques |
| Une base **locale** en développement (`make db-up`) | idem ; et des migrations appliquées « à la main » qui désynchronisent le schéma |
| Variables **injectées** en production, jamais de fichier de secrets sur le serveur | fuite d'un `.env` dans une image ou un dépôt |
| **Avant toute commande qui écrit en base, fixer la cible** (`ENVIRONMENT=ci` + `DATABASE_URL` explicite) ; jamais de script destructif « pour voir » ; scripts en **aperçu par défaut** + `--confirm` | une suppression lancée sans vérifier la base visée |
| Alembic seul maître du schéma | des tables créées par l'application hors migration, qui bloquent le déploiement suivant |

## Sécurité

| Règle | Le piège évité |
|---|---|
| Refresh tokens **hachés** + rotation + détection de réutilisation | une fuite de la base donnerait toutes les sessions ; un jeton volé resterait utilisable |
| Même réponse pour « e-mail inconnu » et « mauvais mot de passe » (y compris le temps de calcul) | énumération des comptes |
| Statut du compte relu en base à chaque requête | un compte bloqué garderait l'accès jusqu'à l'expiration de son jeton |
| `utc_now()` (`app/core/clock.py`) pour toute date, et ruff `DTZ` qui interdit `datetime.now()` | un `datetime` naïf décalé par le fuseau du serveur : jetons qui expirent à la mauvaise heure |
| Un webhook public exige une **signature** (HMAC, comparaison en temps constant) et refuse tant que le secret n'est pas configuré | n'importe qui pouvait déclencher un événement de confiance |
| Les montants et états sensibles sont **calculés côté serveur** | un client qui impose son propre montant |
| Les attributions « premier arrivé » sont des `UPDATE` conditionnels atomiques | deux utilisateurs obtenant la même ressource |
| Ressource d'autrui = **404** | révéler l'existence d'un objet |

## Limitation de débit

| Règle | Le piège évité |
|---|---|
| Redis dès que `workers > 1` | une limite « 5/min » devenue « 5/min **par worker** » |
| **Fail-open** si Redis tombe | une panne de cache qui coupe toute l'API |
| Middleware maison plutôt que le middleware de la bibliothèque (`slowapi`) | le middleware d'origine plantait quand Redis était coupé et ignorait les handlers asynchrones |
| La fixture `rate_limit` **sauvegarde et restaure** l'état global du limiteur | un test qui change les limites par défaut fausse silencieusement tous les suivants |

## API

| Règle | Le piège évité |
|---|---|
| **Toute liste paginée**, avec garde-fou en test | une table entière renvoyée, qui fait tomber le serveur quand les données grossissent |
| Tri en liste blanche + départage par `id` | tri sur un champ sensible ; doublons/oublis entre deux pages |
| `400` (et non `422`) pour toute entrée invalide | deux codes à gérer côté client |
| `null` explicite sur une colonne obligatoire → **400** | un `PATCH {"name": null}` qui provoque un 500 |
| Routes statiques déclarées **avant** les routes dynamiques | `/history` masquée par `/{id}` (« introuvable ») |
| Ne jamais renvoyer un `UUID` brut dans un `JSONResponse` | sérialisation impossible : 500 systématique (passer par un `response_model`) |
| Erreurs `500` génériques | fuite de détails internes |

## Services tiers

| Règle | Le piège évité |
|---|---|
| Chaque service tiers se choisit par une variable `*_BACKEND` ; ses paramètres sont exigés **quand il est choisi** | un SMTP ou un bucket mal configuré découvert au premier envoi, en production |
| Backend de développement **refusé** en production (`EMAIL_BACKEND=console`, `STORAGE_BACKEND=local`) | des e-mails jamais envoyés, des fichiers perdus à chaque déploiement |
| Validation de **signature réelle** des fichiers, nom aléatoire, chemin résolu sous la racine | un script déguisé en image, une traversée de répertoire |
| Les erreurs d'un tiers sont enveloppées sans leur message | un mot de passe SMTP qui finit dans les logs |
| Les tests de tiers n'utilisent **jamais le réseau** | des tests lents, instables, qui dépendent de comptes réels |

## Données et transactions

| Règle | Le piège évité |
|---|---|
| Une requête = une transaction, un seul `commit()` | un état à moitié écrit après une erreur |
| `AuditService.snapshot` **avant** les effets de bord | un « avant » qui contient déjà le « après » |
| Agrégations SQL plutôt que calculs en Python | des tableaux de bord dont le coût croît avec les données |
| `like_pattern()` pour les recherches | `%` et `_` interprétés comme jokers |
| Suppression **logique** des comptes | un historique cassé par des clés étrangères |

## Qualité et pipeline

| Règle | Le piège évité |
|---|---|
| `.env.example` synchronisé avec `Settings` par un test | une variable ajoutée au code et oubliée dans la documentation (ou l'inverse) |
| Les migrations sont **lintées et formatées** (hook Alembic) | des diffs de style dans les revues, un hook de commit qui bloque sur un fichier généré |
| Les garde-fous sont des **tests** (matrice RBAC, complétude de l'audit, contrat OpenAPI) | une route oubliée, non protégée ou non tracée, que la relecture ne voit pas |
| `test_session_lifecycle` : une vraie session par requête | une relation lue après fermeture de la session : verte en test, 500 en production |
| Tester les **refus** et l'**isolation** entre utilisateurs, pas que le cas heureux | un endpoint qui laisse lire les données d'autrui |
| Vérifier une règle en la **cassant volontairement** (test de mutation manuel) | un test qui passe quoi qu'il arrive |
| Suite aussi lancée sur **PostgreSQL** en CI | ce que SQLite ne montre pas : enums, JSONB, verrous, agrégations |
| Migrations : base vierge, `alembic check`, retour arrière **et rejeu**, **une seule tête** | une migration non rejouable (types enum PostgreSQL oubliés dans `downgrade`) |
| `mypy` bloquant, `col()` / `eager()` pour SQLModel | des erreurs de type masquées par un typage progressif jamais terminé |
| Un `# type: ignore` doit rester **sur la ligne** qu'il concerne | le formateur le séparait de sa ligne : mypy échouait au push |
| Activer le **venv** avant de committer | hooks `ruff` / `mypy` en échec (`No module named ruff`) |
| `# gitleaks:allow` sur les fausses valeurs de test, jamais d'affaiblissement du hook | secrets de test pris pour de vrais |
| Pas de `print()` dans `app/` — ruff `T20` le **refuse** | un `print` de débogage oublié qui s'affiche à chaque import en production |

## Hygiène de dépôt

- Jamais de `.env*` committé (sauf `.env.example`).
- `API_REFERENCE.md` est **généré** : ne jamais l'éditer à la main.
- Les imports de `app/modules/__init__.py` sont un **registre de modèles** : ne pas les « nettoyer ».
- Commits atomiques ; hooks jamais contournés (`--no-verify`) pour « aller plus vite ».
