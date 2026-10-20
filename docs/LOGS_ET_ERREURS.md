# Erreurs renvoyées au client et logs

Deux sujets liés par un même fil : l'**identifiant de requête** (`request_id`). Le client reçoit une erreur propre ;
l'équipe retrouve toute l'histoire dans les logs, Sentry et l'audit grâce à cet identifiant.

---

## 1. Le format d'erreur

Toute erreur a **la même forme** (`app/core/errors.py`) :

```json
{
  "error": {
    "code": "validation_error",
    "message": "Les données envoyées sont invalides",
    "status": 400,
    "request_id": "9f2c1d0e7a4b4f4f9c2e5a1b8d7c6e5f",
    "details": [
      { "field": "body.name", "message": "Valeur trop courte", "code": "string_too_short" }
    ]
  }
}
```

| Champ | Rôle | Pour qui |
|---|---|---|
| `code` | identifiant **stable** de l'erreur (`invalid_credentials`, `not_found`…) | le **code client** : un `switch` dessus |
| `message` | phrase lisible, en français | l'utilisateur final (peut être reformulée : ne pas s'y fier dans le code) |
| `status` | rappel du code HTTP | confort |
| `request_id` | identifiant de la requête (aussi dans l'en-tête `X-Request-ID`) | le support : « donnez-moi cet identifiant » |
| `details` | liste `{field, message, code}` des champs invalides, sinon `null` | formulaires |
| `debug` | type d'exception et trace — **uniquement si `ERROR_DEBUG`** (local/ci par défaut) | le développeur |

**Règles** :

1. Le client se base sur **`code`**, jamais sur `message`.
2. Une erreur **5xx** ne révèle rien : `internal_error` + message générique. La cause est dans les logs et Sentry.
3. Une **valeur saisie** n'est jamais renvoyée : un mot de passe mal formé ne revient pas dans `details`.
4. Les en-têtes utiles sont conservés : `Retry-After` (429), `WWW-Authenticate` (401).
5. Tout est en JSON, y compris les erreurs du framework (route inconnue, méthode non autorisée, corps illisible).

### Détail technique : visible ou non selon l'environnement

| Environnement | `debug` dans la réponse (`ERROR_DEBUG` vide) |
|---|---|
| `local`, `ci` | **oui** (type, message et trace de l'exception) |
| `staging` | non (activable ponctuellement : `ERROR_DEBUG=true`) |
| `production` | **non, jamais** — `ERROR_DEBUG=true` empêche le démarrage |

### Les codes

| Code | HTTP | Quand |
|---|---|---|
| `validation_error` | 400 | données invalides (`details` par champ) |
| `bad_request` | 400 | requête incorrecte sans code plus précis |
| `invalid_sort`, `invalid_date_range` | 400 | paramètres de liste |
| `weak_password` | 400 | mot de passe hors politique |
| `invalid_file` | 400/415 | fichier de contenu invalide |
| `unauthorized` | 401 | authentification absente |
| `invalid_credentials` | 401 | e-mail inconnu **ou** mauvais mot de passe (volontairement indiscernables) |
| `invalid_token`, `token_expired` | 401 | jeton invalide / expiré |
| `forbidden`, `filter_forbidden` | 403 | permission ou filtre interdit |
| `account_blocked`, `registration_closed` | 403 | compte suspendu, inscription fermée |
| `not_found` | 404 | ressource introuvable (**aussi** celle d'autrui) |
| `method_not_allowed` | 405 | |
| `conflict`, `email_already_used`, `invalid_state_transition`, `resource_locked` | 409 | conflit d'état |
| `payload_too_large` | 413 | fichier trop gros |
| `unsupported_media_type` | 415 | type de fichier interdit |
| `rate_limited`, `account_locked` | 429 | limite de débit / verrou de compte (`Retry-After`) |
| `internal_error` | 500 | erreur interne (générique) |
| `service_unavailable`, `storage_unavailable` | 503 | dépendance indisponible |

### Lever une erreur

```python
from app.core.errors import AppError, ErrorCode

raise AppError(404, ErrorCode.NOT_FOUND, "Projet introuvable")
raise AppError(409, ErrorCode.INVALID_STATE_TRANSITION, "Transition interdite : archived → active")
raise AppError(400, ErrorCode.VALIDATION_ERROR, "…", details=[{"field": "body.name", "message": "…", "code": "…"}])
raise AppError(429, ErrorCode.ACCOUNT_LOCKED, "…", headers={"Retry-After": "60"})
```

`AppError` est une `HTTPException` : le code existant et les tests qui l'attendent continuent de fonctionner.
**Un nouveau cas d'erreur = un nouveau `ErrorCode`** (valeur stable : une fois publiée, on ne la renomme plus).
Documenter les statuts d'une route avec `responses=err(401, 403, 404)`.

### Côté client (exemple)

```ts
const { error } = await response.json()
switch (error.code) {
  case "invalid_credentials": showLoginError(); break
  case "account_locked": showCountdown(response.headers.get("Retry-After")); break
  case "validation_error": error.details.forEach(d => form.setError(d.field, d.message)); break
  default: showGenericError(`Référence : ${error.request_id}`)
}
```

---

## 2. Les logs

Un log sert à **comprendre ce qui s'est passé** (diagnostic), pas à garder une trace légale : pour cela, il y a
l'audit (`docs/AUDIT.md`), qui est distinct.

### Comportement par environnement

| | `local` | `ci` | `staging` | `production` |
|---|---|---|---|---|
| Niveau par défaut | DEBUG | INFO | INFO | INFO |
| Format | texte lisible | texte lisible | **JSON** | **JSON** |
| Traces d'appels dans les logs | oui | oui | oui | **non** (Sentry les porte) |
| Détail technique dans la réponse | oui | oui | non | **jamais** |

Tout se surcharge (`.env.example`) : `LOG_LEVEL`, `LOG_FORMAT` (`auto`/`text`/`json`), `LOG_STACKTRACES`, `ERROR_DEBUG`.
Au démarrage, l'application journalise sa politique effective (`event: app.started`).

> **Pourquoi pas de trace en production ?** Le message d'une exception contient souvent des données (e-mail,
> identifiant, fragment de requête). Sans trace, seul le **type** de l'exception est journalisé ; Sentry reçoit la trace complète.
> Si votre projet n'a pas Sentry, activez `LOG_STACKTRACES=true` en connaissance de cause.

### Les niveaux

| Niveau | Quand | Exemple |
|---|---|---|
| `DEBUG` | diagnostic fin, désactivé en production | valeur intermédiaire d'un calcul |
| `INFO` | fonctionnement **normal**, y compris les **succès** | `auth.login.succeeded`, `http.request` 200 |
| `WARNING` | anormal mais **géré** : refus, échec de connexion, requête 4xx | `auth.login.failed`, `auth.token.reuse_detected` |
| `ERROR` | une opération a échoué **par notre faute** | `error.unhandled`, requête 5xx |
| `CRITICAL` | le service ne peut plus fonctionner | base inaccessible au démarrage |

### Une ligne par événement, avec des champs

```python
import logging
logger = logging.getLogger(__name__)

logger.info("Projet créé", extra={"event": "project.created", "project_id": str(project.id), "user_id": str(user.id)})
logger.warning("Connexion refusée", extra={"event": "auth.login.failed", "reason": "bad_password"})
```

Sortie JSON (staging/production) :

```json
{"ts":"2026-10-20T21:30:02+00:00","level":"WARNING","logger":"app.modules.auth.service","message":"Connexion refusée",
 "service":"FastAPI Backend Template","env":"production","request_id":"9f2c…","event":"auth.login.failed","reason":"bad_password"}
```

Sortie texte (local) : `21:30:02 WARNING  app.modules.auth.service: Connexion refusée  request_id=9f2c… event=auth.login.failed reason=bad_password`

**Conventions**

- `event` = `domaine.action[.résultat]` en minuscules (`auth.login.succeeded`, `project.deleted`) : nom **stable**, filtrable (`jq 'select(.event=="auth.login.failed")'`).
- Les champs sont des **identifiants** (`user_id`, `project_id`), pas des données personnelles.
- Le **`request_id`** est ajouté automatiquement à chaque ligne.
- Message en français, court, sans variable dedans : les variables vont dans les champs (`extra`).
- « Succès » = `INFO` avec un `event` qui se termine par `.succeeded`/`.created`… Il n'y a pas de niveau `SUCCESS`.

### Le journal d'accès

Une ligne par requête (`event: http.request`) : `method`, `path`, `status`, `duration_ms`, `user_id`, `request_id`.
Niveau selon l'issue : **INFO** (< 400), **WARNING** (4xx), **ERROR** (5xx). La *query string* n'est jamais journalisée
(elle peut contenir un jeton), ni les en-têtes, ni le corps. Les sondes `/health` sont ignorées. Le journal d'accès
d'uvicorn est coupé (sinon chaque requête serait écrite deux fois).

### Ce qu'on ne logge jamais

Mot de passe, jeton, clé d'API, e-mail ou autre donnée personnelle, corps de requête, en-têtes d'autorisation.
Filet de sécurité : `app/core/redaction.py` masque automatiquement les clés sensibles (`password`, `token`,
`authorization`, `api_key`…) dans les champs `extra` — **mais le premier réflexe est de ne pas les passer**.
Ajouter toute nouvelle clé sensible à `SENSITIVE_KEYS` (partagé avec l'audit).

---

## 3. Retrouver une histoire (le fil du `request_id`)

Un utilisateur signale une erreur et donne `request_id: 9f2c…` (ou l'en-tête `X-Request-ID`) :

```bash
# logs structurés (staging/production)
docker logs api 2>&1 | jq -c 'select(.request_id=="9f2c…")'
# Sentry : étiquette « request_id »
# audit (ce que la requête a modifié)
GET /api/v1/admin/audit-logs?request_id=9f2c…
```

On voit : la ligne d'accès (statut, durée, utilisateur), l'éventuelle erreur (`error.unhandled` + type d'exception),
les événements métier, et les entrées d'audit — tout relié par le même identifiant.

---

## 4. Logs ou audit ?

| | Logs | Audit |
|---|---|---|
| But | diagnostiquer, surveiller | prouver qui a fait quoi |
| Stockage | sortie standard, agrégateur (rotation) | table en ajout seul (conservée) |
| Contenu | événements techniques et métier, volatils | opérations, avant/après, acteur |
| Peut disparaître | oui | non |
| Données personnelles | à éviter | seulement l'utile (identifiants) |

Une opération importante a **les deux** : une entrée d'audit (preuve) et, si utile, un log (diagnostic).
