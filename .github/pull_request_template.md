## Résumé

<!-- Quoi et POURQUOI (le diff dit déjà comment). Lien vers le ticket si besoin. -->

## Type de changement

- [ ] Nouvelle fonctionnalité / module
- [ ] Correction de bug (joindre le test qui échouait avant)
- [ ] Migration de schéma
- [ ] Sécurité
- [ ] Documentation / outillage

## Checklist (cocher, ou barrer avec une raison)

**Rigueur**
- [ ] `make check` est vert en local (lint + types + tests + couverture)
- [ ] Aucun `# type: ignore`, `# noqa` ou `--no-verify` ajouté sans justification écrite
- [ ] L'architecture est respectée : logique dans `service.py`, jamais dans `router.py` (`docs/ARCHITECTURE.md`)

**Tests**
- [ ] Cas nominal **et** refus d'accès (403), isolation entre utilisateurs, entrées invalides, conflits d'état
- [ ] Les garde-fous sont à jour : matrice d'accès, décisions d'audit, contrat OpenAPI
- [ ] Un bug corrigé a un test de non-régression

**Sécurité**
- [ ] Toute nouvelle route déclare une permission (`Requires` / `RequiresAny`)
- [ ] Aucun secret dans le code, les logs, les messages d'erreur ou les tests (hors valeurs factices `gitleaks:allow`)
- [ ] Toute opération qui écrit est tracée dans l'audit

**Migrations** (si le schéma change)
- [ ] Migration générée (`make rev`), **relue**, et son `downgrade` fonctionne (enums PostgreSQL supprimés)
- [ ] Colonne obligatoire ajoutée à une table existante : valeur par défaut ou migration de données prévue
- [ ] `make drift` ne signale rien

**Documentation**
- [ ] `make docs` exécuté si des routes ont changé · `.env.example` à jour si une variable a changé
