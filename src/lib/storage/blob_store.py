from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# Los objetos se nombran <tipo>/<uid>/<resto>: el uid es el dueño (lo usa la autorización de /files).
#   uploads/<uid>/<photo_id>.<ext>                     fotos subidas con /upload
#   registrations/<uid>/<registration_id>/<pose>.jpg    rostros alineados del registro (+ summary.jpg)
#   results/<uid>/<photo_id>.json                       resultado de /predict de esa foto
OBJECT_KINDS = ("uploads", "registrations", "results")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")


def object_owner(name: str) -> str | None:
    """uid dueño de un objeto, o None si el nombre no tiene el formato esperado."""
    parts = name.split("/")
    if len(parts) < 3 or parts[0] not in OBJECT_KINDS:
        return None
    if not all(_SAFE_SEGMENT.match(part) and ".." not in part for part in parts):
        return None
    return parts[1]


class BlobStore(Protocol):
    def upload(self, name: str, data: bytes, content_type: str) -> None: ...

    def download(self, name: str) -> bytes:
        """Lanza FileNotFoundError si el objeto no existe."""
        ...

    def delete(self, name: str) -> None:
        """No falla si el objeto no existe."""
        ...


class GCSBlobStore:
    """
    Bucket de Google Cloud Storage. Con `impersonate_service_account`, las credenciales por defecto
    (ADC) solo se usan para obtener tokens de esa service account, que tiene permisos únicamente
    sobre los objetos del bucket.
    """

    def __init__(
        self,
        bucket: str,
        project: str | None,
        impersonate_service_account: str | None = None,
        prefix: str = "",
    ) -> None:
        import google.auth
        from google.auth import impersonated_credentials
        from google.cloud import storage

        credentials, default_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        if impersonate_service_account:
            credentials = impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=impersonate_service_account,
                target_scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
            )
        client = storage.Client(project=project or default_project, credentials=credentials)
        # bucket() y no get_bucket(): la service account no tiene storage.buckets.get
        self.bucket = client.bucket(bucket)
        self.prefix = prefix
        logger.info(f"GCS blob store: gs://{bucket}/{prefix} (impersonating {impersonate_service_account})")

    def upload(self, name: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(self.prefix + name).upload_from_string(data, content_type=content_type)

    def download(self, name: str) -> bytes:
        from google.api_core.exceptions import NotFound

        try:
            return self.bucket.blob(self.prefix + name).download_as_bytes()
        except NotFound as exc:
            raise FileNotFoundError(name) from exc

    def delete(self, name: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(self.prefix + name).delete()
        except NotFound:
            pass


class LocalBlobStore:
    """Carpeta local con la misma estructura de nombres (para desarrollo sin GCP)."""

    def __init__(self, root: Path, prefix: str = "") -> None:
        self.root = Path(root) / prefix if prefix else Path(root)
        logger.info(f"Local blob store: {self.root}")

    def _path(self, name: str) -> Path:
        if object_owner(name) is None:
            raise ValueError(f"Invalid object name: {name}")
        return self.root / name

    def upload(self, name: str, data: bytes, content_type: str) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)
