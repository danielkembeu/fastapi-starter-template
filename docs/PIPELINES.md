# Pipelines : de la modification à la production

Le chemin d'un changement est toujours le même, qu'il vienne d'une personne ou d'une IA :

```text
 poste ──commit──▶ poste ──push──▶ PR ───────▶ main ──tag v*──▶ staging ──approbation──▶ production
        hooks rapides   hooks complets   CI complète   branche protégée   image + migrations   humain
```

Chaque étape **refuse** ce qui est dangereux ; aucune ne dépend de la bonne volonté de quelqu'un.

## 1. Sur le poste

| Étape | Contrôles | Détail |
|---|---|---|
| `git commit` | secrets (gitleaks), hygiène, ruff | < 2 s — `docs/RIGUEUR_DU_CODE.md` |
| `git push` | tête Alembic unique, mypy, `API_REFERENCE.md`, tests + couverture | ~1 min |

## 2. Intégration continue (`.github/workflows/ci.yaml`)

Déclenchée à chaque push et PR sur `main`/`dev`. Les exécutions obsolètes d'une même branche sont annulées.
Permissions minimales (`contents: read`). Aucun secret réel : bases éphémères, valeurs factices.

| Job | Vérifie |
|---|---|
| **quality** | `ruff` (lint + format), `mypy`, `API_REFERENCE.md` à jour |
| **tests** | suite sur SQLite avec couverture ≥ 90 %, puis sur **PostgreSQL** |
| **migrations** | tête unique · `upgrade` sur base vierge · **aucune dérive** modèles/migrations · `downgrade base` puis rejeu · migrations déjà formatées |
| **docker** | l'image se construit, démarre, et `/health/live` répond |
| **security** | `pip-audit` (informatif au départ — à rendre **bloquant** : retirer `continue-on-error`) |

**Un job rouge bloque la fusion.** Pour que ce soit vrai, protéger la branche (voir §4).

Dependabot (`.github/dependabot.yml`) ouvre chaque semaine des PR de mise à jour (pip, actions, Docker) : elles
traversent la même CI, donc une mise à jour qui casse quelque chose est visible avant d'être fusionnée.

## 3. Livraison (`.github/workflows/deploy.yaml`)

Déclenchée par un **tag** `v*` (ou à la main sur une référence précise).

```text
 verify ──▶ image ──▶ staging (automatique) ──▶ production (approbation d'un relecteur)
```

| Job | Rôle |
|---|---|
| `verify` | rejoue `make check` sur le commit étiqueté — on ne livre jamais ce qui n'a pas passé |
| `image` | construit et publie `ghcr.io/<dépôt>:<sha12>` et `:<tag>` (build-arg `EXTRAS="storage mongo"` pour les dépendances optionnelles) |
| `staging` | **À ADAPTER** : migrer puis déployer sur staging |
| `production` | **À ADAPTER** : idem, derrière l'approbation d'un relecteur |

**Sécurité par défaut** : tant que les étapes « À ADAPTER » ne sont pas remplies, elles **échouent bruyamment** (`exit 1`).
Un pipeline de déploiement qui « réussit » sans rien déployer est pire qu'un pipeline cassé.

### Ordre d'un déploiement (à reproduire dans les étapes à adapter)

1. **Sauvegarde** de la base (production : toujours).
2. `alembic upgrade head` sur la base cible, **avant** la nouvelle image. La migration doit rester compatible avec l'ancienne version du code (voir `docs/MIGRATIONS.md`).
3. Démarrer la nouvelle image avec les variables de l'environnement (jamais de fichier `.env` sur le serveur).
4. **Attendre `GET /health/ready` = 200** (base joignable, Redis si utilisé, schéma à la bonne révision).
5. Basculer le trafic, puis retirer l'ancienne version.
6. En cas d'échec à l'étape 4 : ne pas basculer, journaliser, revenir à l'image précédente.

### Exemples d'étape de déploiement

*Serveur unique (SSH + compose)* :

```yaml
- uses: appleboy/ssh-action@v1          # à épingler sur un SHA en production
  with:
    host: ${{ secrets.DEPLOY_HOST }}
    username: ${{ secrets.DEPLOY_USER }}
    key: ${{ secrets.DEPLOY_SSH_KEY }}
    script: |
      cd /srv/app && docker compose pull api
      docker compose run --rm api alembic upgrade head
      docker compose up -d api
      for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health/ready && exit 0; sleep 2; done; exit 1
```

*Plateforme managée* : exécuter `alembic upgrade head` en commande de pré-déploiement (« release command »), puis
configurer `GET /health/ready` comme contrôle de santé.

## 4. Configuration GitHub à faire une fois par dépôt

| Réglage | Valeur | Pourquoi |
|---|---|---|
| **Protection de `main`** | PR obligatoire · jobs `quality`, `tests`, `migrations`, `docker` requis · branche à jour · pas de push direct · pas de force-push | la CI devient une barrière |
| **Environments** `staging`, `production` | secrets et variables **par environnement** ; `production` avec *Required reviewers* | l'approbation humaine avant production |
| **Secrets** | uniquement dans les Environments (jamais au niveau dépôt pour la production) | un secret de production n'est lisible que par le job de production |
| **Dependabot / secret scanning / push protection** | activés | détecte les secrets et dépendances vulnérables côté GitHub, en plus de gitleaks |
| **Actions tierces** | épinglées sur un SHA (production) | une action compromise ne peut pas changer sous vos pieds |

## 5. Variables par environnement

Un jeu de variables **par Environment GitHub** (staging ≠ production) : `DATABASE_URL`, `SECRET_JWT` (32+ caractères
aléatoires, différent par environnement), `CORS_ORIGINS`, `SMTP_*`, `S3_*`/`CLOUDINARY_*`, `SENTRY_DSN`,
`RATE_LIMIT_STORAGE_URI` (Redis), `DOCS_USERNAME/PASSWORD` (staging), `HEALTH_DETAIL_TOKEN`. Les verrous de
démarrage refusent une configuration dangereuse : un déploiement mal configuré **échoue au démarrage**, il n'expose rien.

## 6. Versions et retour arrière

- **Versionnage** : tags sémantiques `vMAJEUR.MINEUR.CORRECTIF` ; chaque tag correspond à une image immuable.
- **Retour arrière applicatif** : redéployer le tag précédent (l'image existe toujours).
- **Retour arrière de schéma** : seulement si la migration est réversible et qu'aucune donnée utile n'est perdue
  (sinon restaurer la sauvegarde). C'est pourquoi les migrations doivent être compatibles avec la version précédente.
- **Correctif urgent** : branche depuis le tag de production → PR → tag de correctif. La CI s'applique, même en urgence.

## 7. Ce qu'on ajoute ensuite

Analyse statique de sécurité (CodeQL), signature d'image (cosign) et SBOM, tests de charge/de fumée post-déploiement,
alertes sur `/health/ready`, déploiement progressif (canari). À ajouter quand le projet le justifie, jamais en
remplacement des contrôles ci-dessus.
