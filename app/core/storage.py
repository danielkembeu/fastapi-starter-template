"""Stockage de fichiers, selon `STORAGE_BACKEND` : local, cloudinary, s3 ou disabled.

Interface unique : `get_storage().save(...)` / `.delete(key)`. Les services ne connaissent jamais le
fournisseur. Cloudinary et S3 sont des dépendances **optionnelles** (`requirements-storage.txt`),
importées paresseusement.

Règles de sécurité appliquées avant tout stockage (`validate_upload`) : taille maximale, type MIME
autorisé et **signature réelle du fichier** (le type annoncé par le client ne prouve rien).
"""

import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import StorageBackend, settings
from app.core.errors import AppError, ErrorCode

# Signatures ("magic bytes") des types acceptés.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
_SAFE_PART = re.compile(r"[^A-Za-z0-9._-]")
_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@dataclass(frozen=True)
class StoredFile:
    key: str  # identifiant à conserver en base pour supprimer le fichier plus tard
    url: str


class Storage(Protocol):
    def save(self, data: bytes, *, folder: str, content_type: str) -> StoredFile: ...

    def delete(self, key: str) -> None: ...


def validate_upload(data: bytes, content_type: str) -> None:
    """Refuse un fichier trop gros, d'un type non autorisé ou dont le contenu ne correspond pas."""
    if len(data) > settings.UPLOAD_MAX_BYTES:
        raise AppError(413, ErrorCode.PAYLOAD_TOO_LARGE, "Fichier trop volumineux")
    if content_type not in settings.upload_allowed_types:
        raise AppError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Type de fichier non supporté")
    signatures = _SIGNATURES.get(content_type)
    if signatures and not data.startswith(signatures):
        raise AppError(
            415, ErrorCode.INVALID_FILE, "Le contenu du fichier ne correspond pas à son type"
        )


def _safe_key(folder: str, content_type: str) -> str:
    # Nom aléatoire : jamais le nom envoyé par le client (traversée de répertoire, écrasement).
    name = secrets.token_urlsafe(16) + _EXTENSIONS.get(content_type, "")
    return f"{_SAFE_PART.sub('_', folder).strip('._') or 'files'}/{name}"


class LocalStorage:
    """Disque local — développement et tests uniquement (refusé en staging/production)."""

    def __init__(self, root: str, public_url: str):
        self.root = Path(root).resolve()
        self.public_url = public_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise AppError(400, ErrorCode.INVALID_FILE, "Chemin de fichier invalide")
        return path

    def save(self, data: bytes, *, folder: str, content_type: str) -> StoredFile:
        key = _safe_key(folder, content_type)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredFile(key=key, url=f"{self.public_url}/{key}")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class CloudinaryStorage:
    def __init__(self) -> None:
        import cloudinary

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

    def save(self, data: bytes, *, folder: str, content_type: str) -> StoredFile:
        import cloudinary.uploader

        key = _safe_key(folder, content_type).rsplit(".", 1)[0]
        result = cloudinary.uploader.upload(data, public_id=key, overwrite=False)
        return StoredFile(key=result["public_id"], url=result["secure_url"])

    def delete(self, key: str) -> None:
        import cloudinary.uploader

        cloudinary.uploader.destroy(key)


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self.client = boto3.client(
            "s3",
            region_name=settings.S3_REGION or None,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        )

    def save(self, data: bytes, *, folder: str, content_type: str) -> StoredFile:
        key = _safe_key(folder, content_type)
        self.client.put_object(
            Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=content_type
        )
        base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
        url = f"{base}/{key}" if base else f"https://{settings.S3_BUCKET}.s3.amazonaws.com/{key}"
        return StoredFile(key=key, url=url)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=settings.S3_BUCKET, Key=key)


def get_storage() -> Storage:
    backend = settings.STORAGE_BACKEND
    if backend is StorageBackend.LOCAL:
        return LocalStorage(settings.STORAGE_LOCAL_PATH, settings.STORAGE_LOCAL_PUBLIC_URL)
    if backend is StorageBackend.CLOUDINARY:
        return CloudinaryStorage()
    if backend is StorageBackend.S3:
        return S3Storage()
    raise AppError(503, ErrorCode.STORAGE_UNAVAILABLE, "Stockage de fichiers non configuré")
