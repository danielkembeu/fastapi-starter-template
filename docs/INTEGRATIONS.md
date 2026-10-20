# Intégrations : e-mail et stockage de fichiers

Les services tiers passent par une **interface unique** : un module métier ne connaît jamais le fournisseur. Changer de
fournisseur = changer une variable d'environnement.

## E-mail (`app/core/email.py`)

```dotenv
EMAIL_BACKEND=smtp            # console | smtp | disabled
EMAIL_FROM=no-reply@exemple.com
SMTP_HOST=smtp.exemple.com
SMTP_PORT=587
SMTP_USERNAME=…
SMTP_PASSWORD=…
SMTP_USE_TLS=true             # STARTTLS (587) — ou SMTP_USE_SSL=true (465) ; exclusifs
```

| Backend | Usage | Remarque |
|---|---|---|
| `console` | développement, tests | journalise le message ; **refusé en staging/production** (il n'enverrait rien) |
| `smtp` | production | `smtplib` de la bibliothèque standard, délai d'attente (`SMTP_TIMEOUT_SECONDS`) |
| `disabled` | projet sans e-mail | tout envoi lève `EmailError` (erreur de programmation) |

```python
from app.core.email import Email, EmailError, send_email

# dans un service, APRÈS le commit de l'opération (un e-mail ne s'annule pas)
try:
    send_email(Email(to=user.email, subject="Bienvenue", text="…", html="<p>…</p>"))
except EmailError:
    logger.warning("E-mail de bienvenue non envoyé", extra={"user_id": str(user.id)})
```

Sécurité :
- Les retours à la ligne dans le destinataire ou le sujet sont **refusés** (injection d'en-têtes, ex. `Bcc:` caché).
- Une panne SMTP lève une erreur **générique** ; le message du serveur (qui peut contenir des identifiants) n'est jamais journalisé.
- Ne jamais mettre de secret, de jeton long ou de mot de passe dans un e-mail ; préférer un lien à usage unique et court.
- Envoyer sans bloquer la réponse HTTP : pour un volume important, passer par une file de tâches (non fournie).
- En développement : `make up PROFILES="mail"` lance une boîte mail qui capte tout (`http://127.0.0.1:58025`), avec `SMTP_HOST=127.0.0.1`, `SMTP_PORT=51025`, `SMTP_USE_TLS=false`.

## Stockage de fichiers (`app/core/storage.py`)

```dotenv
STORAGE_BACKEND=s3            # disabled | local | cloudinary | s3
UPLOAD_MAX_BYTES=5242880
UPLOAD_ALLOWED_TYPES=image/jpeg,image/png,image/webp
```

| Backend | Variables requises | Installation |
|---|---|---|
| `local` | `STORAGE_LOCAL_PATH`, `STORAGE_LOCAL_PUBLIC_URL` | — · **refusé en staging/production** (disque éphémère) |
| `cloudinary` | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | `make install-extras EXTRAS="storage"` |
| `s3` | `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` · optionnels `S3_REGION`, `S3_ENDPOINT_URL`, `S3_PUBLIC_BASE_URL` | `make install-extras EXTRAS="storage"` |
| `disabled` | — | tout usage répond `503` |

`s3` couvre AWS S3 **et** tout stockage compatible (MinIO, Scaleway, Cloudflare R2…) via `S3_ENDPOINT_URL`.
En développement : `make up PROFILES="storage"` lance MinIO (`S3_ENDPOINT_URL=http://127.0.0.1:59000`).

```python
from fastapi import UploadFile
from app.core.storage import get_storage, validate_upload

async def update_avatar(session, user, image: UploadFile):
    data = await image.read()
    validate_upload(data, image.content_type or "")       # 413 / 415 si refusé
    stored = get_storage().save(data, folder="avatars", content_type=image.content_type)
    user.avatar_key, user.avatar_url = stored.key, stored.url   # conserver la clé pour supprimer plus tard
    ...
```

Sécurité (déjà appliquée par `validate_upload` et les adaptateurs) :

| Risque | Protection |
|---|---|
| Fichier géant | `UPLOAD_MAX_BYTES` → `413` |
| Type interdit | liste blanche `UPLOAD_ALLOWED_TYPES` → `415` |
| Faux type (un script déclaré « image/png ») | **vérification de la signature réelle** du fichier → `415` |
| Nom de fichier malveillant (`../../etc/passwd`) | le nom du client n'est **jamais** utilisé : nom aléatoire |
| Traversée de répertoire (stockage local) | chemin résolu et vérifié sous la racine |
| Écrasement d'un fichier existant | noms uniques ; `overwrite=False` (Cloudinary) |

À ajouter selon le projet : analyse antivirus, redimensionnement/ré-encodage des images (supprime les métadonnées EXIF
et les charges cachées), URLs signées à durée limitée pour les fichiers privés, quotas par utilisateur.

## Ajouter une intégration

1. Variables dans `Settings` (typées, avec défaut sûr) et dans `.env.example` (test de synchronisation).
2. **Verrous** : paramètres requis quand le backend est choisi ; backend dangereux refusé en production (`tests/core/test_config.py`).
3. Un module `app/core/<service>.py` avec une **interface** et des adaptateurs ; imports de SDK **paresseux** (dépendance optionnelle dans `requirements-<service>.txt`).
4. **Tests sans réseau** : faux client injecté ; erreurs enveloppées sans fuite d'identifiants.
5. Ne **pas** ajouter le service à `/health/ready` s'il n'est pas vital (sa panne ne doit pas retirer l'API de la rotation) ; l'ajouter s'il l'est.
6. Documenter ici.
