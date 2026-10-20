"""Stockage de fichiers : validation stricte, noms imprévisibles, aucun accès hors du dossier."""

import sys
import types

import pytest
from fastapi import HTTPException

from app.core import storage as storage_module
from app.core.config import StorageBackend
from app.core.storage import LocalStorage, get_storage, validate_upload

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff" + b"\x00" * 32


@pytest.fixture(name="configure")
def configure_fixture(monkeypatch):
    def apply(**values):
        for key, value in values.items():
            monkeypatch.setattr(f"app.core.config.settings.{key}", value)

    return apply


# ---- Validation ----------------------------------------------------------------------


def test_valid_images_are_accepted():
    validate_upload(PNG, "image/png")
    validate_upload(JPEG, "image/jpeg")


@pytest.mark.parametrize(
    ("data", "content_type", "status"),
    [
        (PNG, "application/x-sh", 415),  # type non autorisé
        (PNG, "text/html", 415),
        (b"<?php echo 1;", "image/png", 415),  # annonce PNG, contenu PHP
        (JPEG, "image/png", 415),  # signature d'un autre type
    ],
)
def test_forbidden_or_lying_files_are_refused(data, content_type, status):
    with pytest.raises(HTTPException) as refused:
        validate_upload(data, content_type)
    assert refused.value.status_code == status


def test_oversized_files_are_refused_with_413(configure):
    configure(UPLOAD_MAX_BYTES=10)
    with pytest.raises(HTTPException) as refused:
        validate_upload(PNG, "image/png")
    assert refused.value.status_code == 413


# ---- Disque local --------------------------------------------------------------------


def test_local_storage_writes_under_its_root_with_a_random_name(tmp_path):
    storage = LocalStorage(str(tmp_path), "http://files.test/up")
    stored = storage.save(PNG, folder="avatars", content_type="image/png")

    assert stored.key.startswith("avatars/") and stored.key.endswith(".png")
    assert stored.url == f"http://files.test/up/{stored.key}"
    assert (tmp_path / stored.key).read_bytes() == PNG
    other = storage.save(PNG, folder="avatars", content_type="image/png")
    assert other.key != stored.key  # jamais deux fois le même nom


@pytest.mark.parametrize("folder", ["../../etc", "/etc", "a/../../b", "..", "x\x00y"])
def test_a_hostile_folder_cannot_escape_the_storage_root(tmp_path, folder):
    storage = LocalStorage(str(tmp_path), "http://files.test")
    stored = storage.save(PNG, folder=folder, content_type="image/png")
    assert (tmp_path / stored.key).resolve().is_relative_to(tmp_path.resolve())


def test_delete_cannot_reach_outside_the_root_and_is_idempotent(tmp_path):
    outside = tmp_path.parent / "precious.txt"
    outside.write_text("garde-moi")
    storage = LocalStorage(str(tmp_path), "http://files.test")

    with pytest.raises(HTTPException):
        storage.delete("../precious.txt")
    assert outside.exists()

    stored = storage.save(PNG, folder="f", content_type="image/png")
    storage.delete(stored.key)
    storage.delete(stored.key)  # déjà supprimé : sans erreur
    assert not (tmp_path / stored.key).exists()


# ---- Choix du backend ----------------------------------------------------------------


def test_disabled_storage_answers_503(configure):
    configure(STORAGE_BACKEND=StorageBackend.DISABLED)
    with pytest.raises(HTTPException) as refused:
        get_storage()
    assert refused.value.status_code == 503


def test_local_backend_is_selected_by_configuration(configure, tmp_path):
    configure(STORAGE_BACKEND=StorageBackend.LOCAL, STORAGE_LOCAL_PATH=str(tmp_path))
    assert isinstance(get_storage(), LocalStorage)


def test_cloudinary_adapter_uses_the_sdk_and_keeps_the_public_id(configure, monkeypatch):
    calls = {}
    uploader = types.SimpleNamespace(
        upload=lambda data, **kw: (
            calls.update(upload=kw) or {"public_id": "p/x", "secure_url": "https://c/x"}
        ),
        destroy=lambda key: calls.update(destroy=key),
    )
    sdk = types.ModuleType("cloudinary")
    sdk.config = lambda **kw: calls.update(config=kw)
    sdk.uploader = uploader
    monkeypatch.setitem(sys.modules, "cloudinary", sdk)
    monkeypatch.setitem(sys.modules, "cloudinary.uploader", uploader)
    configure(
        STORAGE_BACKEND=StorageBackend.CLOUDINARY,
        CLOUDINARY_CLOUD_NAME="demo",
        CLOUDINARY_API_KEY="k",
        CLOUDINARY_API_SECRET="s",
    )

    stored = get_storage().save(PNG, folder="avatars", content_type="image/png")
    get_storage().delete(stored.key)

    assert stored.url == "https://c/x" and stored.key == "p/x"
    assert calls["config"]["cloud_name"] == "demo" and calls["config"]["secure"] is True
    assert calls["upload"]["overwrite"] is False
    assert calls["destroy"] == "p/x"


def test_s3_adapter_uploads_with_the_declared_content_type(configure, monkeypatch):
    calls = {}

    class Client:
        def put_object(self, **kw):
            calls["put"] = kw

        def delete_object(self, **kw):
            calls["delete"] = kw

    sdk = types.ModuleType("boto3")
    sdk.client = lambda name, **kw: calls.update(client=kw) or Client()
    monkeypatch.setitem(sys.modules, "boto3", sdk)
    configure(
        STORAGE_BACKEND=StorageBackend.S3,
        S3_BUCKET="assets",
        S3_REGION="eu-west-3",
        S3_ENDPOINT_URL="https://minio.local",
        S3_ACCESS_KEY_ID="id",
        S3_SECRET_ACCESS_KEY="secret",
        S3_PUBLIC_BASE_URL="https://cdn.example.com/",
    )

    stored = storage_module.get_storage().save(JPEG, folder="docs", content_type="image/jpeg")

    assert calls["client"]["endpoint_url"] == "https://minio.local"
    assert calls["put"]["Bucket"] == "assets" and calls["put"]["ContentType"] == "image/jpeg"
    assert stored.url == f"https://cdn.example.com/{stored.key}"
    storage_module.get_storage().delete(stored.key)
    assert calls["delete"] == {"Bucket": "assets", "Key": stored.key}
