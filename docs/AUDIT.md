# Journal d'audit

Chaque opération laisse une trace : **qui** l'a faite, **quoi**, sur **quelle ressource**, **avant/après**,
**quand**, **d'où** (IP, navigateur, identifiant de requête) et avec **quel résultat**.
Consultation : `GET /api/v1/admin/audit-logs` (permission `audit:read`, rôle administrateur).

## Garanties

| Garantie | Comment | Test |
|---|---|---|
| **Ajout seul** | aucune route ne modifie/supprime une entrée ; en PostgreSQL un déclencheur refuse `UPDATE`, `DELETE`, `TRUNCATE` (même à un script) | `test_there_is_no_way_to_modify…`, `tests/audit/test_audit_db.py` (PostgreSQL) |
| **Atomique avec l'opération** | la trace est écrite dans la même transaction : opération annulée ⇒ aucune trace fantôme | `test_the_entry_is_atomic_with_the_operation` |
| **Refus et échecs tracés** | connexion ratée, 403… écrits dans une transaction indépendante, donc conservés même si la requête échoue | `test_detached_entry_survives_a_rollback…` |
| **Aucun secret** | mots de passe, jetons, signatures masqués (`[masqué]`), même imbriqués | `test_secrets_are_never_written…` |
| **Rien n'échappe** | chaque route qui écrit est déclarée dans `MUTATING_ROUTES` (ou exemptée avec une raison) ; un parcours complet doit produire **chaque** action du catalogue | `tests/audit/test_audit_completeness.py` |
| **Survit à la suppression** | acteur et ressource sont de simples identifiants (pas de clé étrangère) | — |

## Une entrée

| Champ | Sens |
|---|---|
| `created_at` | UTC |
| `actor_type` / `actor_id` / `actor_role` | `user` (authentifié), `system` (tâche automatique, webhook), `anonymous` (connexion ratée…) |
| `action` | catalogue fermé `AuditAction`, ex. `project.created` |
| `outcome` | `success`, `denied` (droits, verrou), `failed` (mauvais mot de passe…) |
| `resource_type` / `resource_id` | type stable (voir `RESOURCE_TYPES`) et identifiant |
| `changes` | `{champ: {from, to}}` des seuls champs modifiés |
| `details` | contexte libre (jamais de secret) |
| `ip_address`, `user_agent`, `request_id` | `request_id` = en-tête `X-Request-ID`, aussi présent dans les logs JSON et Sentry |

## Utiliser l'audit dans un service

```python
before = AuditService.snapshot(project, data.keys())      # AVANT de modifier
...                                                        # modifications
changes = AuditService.diff(before, project)
if changes:
    AuditService.log(session, AuditAction.PROJECT_UPDATED, actor=user, resource=project, changes=changes)
session.commit()                                           # la trace part avec l'opération
```

- Opération **réussie** : `AuditService.log(session, …)` — rejoint la transaction en cours, **ne commit pas**.
- **Refus / échec** (qui lève une erreur HTTP et annule la transaction) : `AuditService.log_detached(…, outcome=AuditOutcome.DENIED)` — session indépendante, ne lève jamais.
- Ne tracer un « avant/après » que si quelque chose a changé.

## Retrouver une histoire

```text
GET /api/v1/admin/audit-logs?resource_type=project&resource_id=<id>&sort=created_at   # toute l'histoire d'une ressource
GET /api/v1/admin/audit-logs?actor_id=<id>                                            # tout ce qu'un utilisateur a fait
GET /api/v1/admin/audit-logs?outcome=denied                                           # incidents de sécurité (ou failed)
GET /api/v1/admin/audit-logs?request_id=<id>                                          # tout ce qu'une requête a déclenché
```

## À savoir

- **Conservation** : le journal grossit sans purge (volontaire). Prévoir un archivage hors ligne avant d'envisager de supprimer.
- Seul un superutilisateur PostgreSQL peut retirer le déclencheur (`DROP TRIGGER`), et ce geste apparaît dans les journaux PostgreSQL.
- Exemptions légitimes (`EXEMPT` dans `MUTATING_ROUTES`) : préférences personnelles, calculs sans effet de bord, télémétrie déjà conservée ailleurs. Toute exemption doit être justifiée par écrit.
