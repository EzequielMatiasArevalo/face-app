from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from lib.auth import CurrentUser, get_current_user
from lib.config import settings
from lib.schemas import (
    AdminPhoto,
    AdminUser,
    AsyncTaskCreated,
    InsertRequest,
    MeResponse,
    PredictRequest,
    RoleUpdate,
    StatusResponse,
    UploadResponse,
)
from lib.services.ai_detector import AIImageDetector
from lib.services.face_service import FaceService
from lib.services.task_manager import TaskManager
from lib.storage.app_db import AppDB
from lib.storage.blob_store import GCSBlobStore, LocalBlobStore, object_owner
from lib.storage.embedding_store import EmbeddingStore
from lib.storage.pgvector_store import PgVectorEmbeddingStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["face-recognition"])
task_manager = TaskManager()
# La inferencia (y la E/S con el bucket de cada job) es sincrónica: corre en un pool de MAX_WORKERS
# hilos para no bloquear el event loop (/status y /me siguen respondiendo mientras se procesa).
inference_pool = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="jobs")

if settings.use_pgvector:
    logger.info("Using PostgreSQL vector store")
    embedding_store = PgVectorEmbeddingStore(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        embedding_dim=settings.embedding_dim,
    )
else:
    logger.info("Using JSON file vector store")
    embedding_store = EmbeddingStore(settings.embeddings_path)

# Usuarios, roles y catálogo de fotos (requiere PostgreSQL aunque los embeddings vayan a JSON)
app_db = AppDB(
    host=settings.postgres_host,
    port=settings.postgres_port,
    dbname=settings.postgres_db,
    user=settings.postgres_user,
    password=settings.postgres_password,
)

if settings.storage_backend == "gcs":
    blob_store = GCSBlobStore(
        bucket=settings.gcs_bucket,
        project=settings.gcs_project,
        impersonate_service_account=settings.gcs_service_account,
        prefix=settings.storage_prefix,
    )
else:
    blob_store = LocalBlobStore(settings.output_path, prefix=settings.storage_prefix)


def _resolved_model_path() -> Path:
    """MODEL_PATH may be a directory; join with MODEL_NAME when set."""
    base = settings.model_path
    name = (settings.model_name or "").strip()
    if name and base.is_dir():
        return base / name
    return base


def _resolved_detector_path() -> Path | None:
    """DETECTOR_MODEL_NAME is optional: unset means the detector does not need a file."""
    name = (settings.detector_model_name or "").strip()
    return settings.model_path / name if name else None


def _resolved_pose_model_path() -> Path | None:
    name = (settings.pose_model_name or "").strip()
    return settings.model_path / name if name else None


face_service = FaceService(
    store=embedding_store,
    similarity_metric=settings.similarity_metric,
    similarity_threshold=settings.similarity_threshold,
    face_size=settings.face_size,
    model_path=_resolved_model_path(),
    blob_store=blob_store,
    detector_path=_resolved_detector_path(),
    det_score_threshold=settings.det_score_threshold,
    det_input_size=settings.det_input_size,
    min_face_size=settings.min_face_size,
    align_margin=settings.align_margin,
    pose_model_path=_resolved_pose_model_path(),
    frontal_max_yaw=settings.frontal_max_yaw,
    profile_min_yaw=settings.profile_min_yaw,
    close_far_min_ratio=settings.close_far_min_ratio,
    registration_min_similarity=settings.registration_min_similarity,
    ai_detector=AIImageDetector(
        settings.model_path / settings.ai_detector_model_name,
        threshold=settings.ai_detection_threshold,
    ),
)

ADMIN_EMAILS = {email.strip().lower() for email in settings.admin_emails.split(",") if email.strip()}
IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


@dataclass(frozen=True)
class Account:
    uid: str
    email: str | None
    name: str | None
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _is_bootstrap_admin(email: str | None, email_verified: bool = True) -> bool:
    """Admin inicial (ADMIN_EMAILS). Exige email verificado: el pool de Auth es compartido."""
    return bool(email) and email_verified and email.lower() in ADMIN_EMAILS


def current_account(user: CurrentUser = Depends(get_current_user)) -> Account:
    """Usuario autenticado con su rol, leído de la base en cada request: un cambio de rol aplica al instante."""
    row = app_db.upsert_user(user.uid, user.email, user.name, _is_bootstrap_admin(user.email, user.email_verified))
    return Account(uid=row["uid"], email=row["email"], name=row["name"], role=row["role"])


def require_admin(account: Account = Depends(current_account)) -> Account:
    if not account.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo para administradores.")
    return account


def _files_url(object_name: str) -> str:
    return f"/files/{object_name}"


def _own_upload(object_name: str, account: Account) -> dict[str, Any]:
    """Solo se procesan imágenes que el propio usuario subió con /upload."""
    photo = app_db.get_photo_by_object(object_name)
    if photo is None or photo["uid"] != account.uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Imagen inválida: {object_name}. Subila primero con /upload.",
        )
    return photo


async def _in_pool(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(inference_pool, fn, *args)


@router.get("/me", response_model=MeResponse)
def me(account: Account = Depends(current_account)) -> MeResponse:
    return MeResponse(
        uid=account.uid,
        email=account.email,
        name=account.name,
        role=account.role,
        face_registered=face_service.is_registered(account.uid),
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...), account: Account = Depends(current_account)
) -> UploadResponse:
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"La imagen supera los {settings.max_upload_mb:g} MB.",
        )
    suffix = Path((file.filename or "").strip()).suffix.lower()
    if suffix not in IMAGE_TYPES:
        suffix = ".jpg"
    photo_id = uuid4().hex
    object_name = f"uploads/{account.uid}/{photo_id}{suffix}"
    await asyncio.to_thread(blob_store.upload, object_name, data, IMAGE_TYPES[suffix])
    await asyncio.to_thread(app_db.add_photo, photo_id, account.uid, object_name, IMAGE_TYPES[suffix], len(data))
    return UploadResponse(path=object_name, download_url=_files_url(object_name))


@router.get("/files/{object_name:path}")
async def download_file(object_name: str, account: Account = Depends(current_account)) -> Response:
    """Imágenes y resultados del bucket: cada usuario ve lo suyo y un admin ve todo."""
    owner = object_owner(object_name)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid object name")
    if owner != account.uid and not account.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="file belongs to another user")
    try:
        data = await asyncio.to_thread(blob_store.download, object_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc
    media, _ = mimetypes.guess_type(object_name)
    return Response(
        content=data,
        media_type=media or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/insert", response_model=AsyncTaskCreated)
async def insert(
    payload: InsertRequest, response: Response, account: Account = Depends(current_account)
) -> AsyncTaskCreated:
    if await asyncio.to_thread(face_service.is_registered, account.uid):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El rostro ya está registrado.")
    objects = payload.images.model_dump()
    photos = {}
    for pose, object_name in objects.items():
        photos[pose] = await asyncio.to_thread(_own_upload, object_name, account)
    await asyncio.to_thread(app_db.mark_registration_attempt, {pose: photo["id"] for pose, photo in photos.items()})
    metadata = {
        **payload.metadata,
        "display_name": account.name or account.email or account.uid,
        "email": account.email,
    }

    def _register() -> str:
        images = {pose: blob_store.download(object_name) for pose, object_name in objects.items()}
        registration_id, summary_object = face_service.register_identity(
            identity=account.uid, images=images, metadata=metadata
        )
        app_db.set_registration_id([photo["id"] for photo in photos.values()], registration_id)
        return summary_object

    response.status_code = status.HTTP_202_ACCEPTED
    job_id = task_manager.create_job(owner=account.uid)

    async def _process() -> str:
        logger.info(f"Registering identity: {account.uid} with images: {objects}")
        return await _in_pool(_register)

    task_manager.schedule(job_id, _process())
    return AsyncTaskCreated(job_id=job_id)


@router.post("/predict", response_model=AsyncTaskCreated)
async def predict(
    payload: PredictRequest, response: Response, account: Account = Depends(current_account)
) -> AsyncTaskCreated:
    if not await asyncio.to_thread(face_service.is_registered, account.uid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primero tenés que completar el registro de tu rostro.",
        )
    photo = await asyncio.to_thread(_own_upload, payload.source_path, account)

    def _predict() -> str:
        result = face_service.predict(blob_store.download(photo["object_name"]), photo["object_name"])
        result_object = f"results/{account.uid}/{photo['id']}.json"
        blob_store.upload(
            result_object,
            json.dumps(result.model_dump(), ensure_ascii=True, indent=2).encode("utf-8"),
            "application/json",
        )
        app_db.set_prediction(photo["id"], result_object, result.ai_detection.is_ai_generated)
        return result_object

    response.status_code = status.HTTP_202_ACCEPTED
    job_id = task_manager.create_job(owner=account.uid, source=photo["object_name"])

    async def _process() -> str:
        logger.info(f"Predicting image: {photo['object_name']}")
        return await _in_pool(_predict)

    task_manager.schedule(job_id, _process())
    return AsyncTaskCreated(job_id=job_id)


@router.get("/status/{job_id}", response_model=StatusResponse)
async def status_by_id(job_id: str, user: CurrentUser = Depends(get_current_user)) -> StatusResponse:
    state = task_manager.get(job_id)
    if state is None or state.owner != user.uid:
        raise HTTPException(status_code=404, detail="job_id not found")
    done = state.status == "done"
    return StatusResponse(
        status=state.status,
        link=state.link,
        reason=state.error,
        artifact_url=_files_url(state.link) if done else None,
        source_image_url=_files_url(state.source) if done and state.source else None,
    )


# --- administración -----------------------------------------------------------------------


def _admin_users() -> list[AdminUser]:
    """Usuarios con cuenta + identidades con embeddings pero sin cuenta (registros previos al login)."""
    face_labels: dict[str, str | None] = {}
    for record in embedding_store.all():
        face_labels.setdefault(record.etiqueta, record.metadata.get("display_name"))
    users = app_db.list_users()
    result = [
        AdminUser(
            uid=user["uid"],
            email=user["email"],
            name=user["name"],
            role=user["role"],
            has_account=True,
            bootstrap_admin=_is_bootstrap_admin(user["email"]),
            face_registered=user["uid"] in face_labels,
            photo_count=user["photo_count"],
            last_seen_at=user["last_seen_at"],
        )
        for user in users
    ]
    accounts = {user["uid"] for user in users}
    result += [
        AdminUser(
            uid=label,
            name=display_name or label,
            has_account=False,
            bootstrap_admin=False,
            face_registered=True,
            photo_count=0,
        )
        for label, display_name in face_labels.items()
        if label not in accounts
    ]
    return result


def _admin_photo(photo: dict[str, Any]) -> AdminPhoto:
    return AdminPhoto(
        id=photo["id"],
        uid=photo["uid"],
        url=_files_url(photo["object_name"]),
        created_at=photo["created_at"],
        kind=photo["kind"],
        pose=photo["pose"],
        active_registration=photo["registration_id"] is not None,
        result_url=_files_url(photo["result_object"]) if photo["result_object"] else None,
        ai_generated=photo["ai_generated"],
        size_bytes=photo["size_bytes"],
    )


@router.get("/admin/users", response_model=list[AdminUser], tags=["admin"])
def admin_list_users(_: Account = Depends(require_admin)) -> list[AdminUser]:
    return _admin_users()


@router.patch("/admin/users/{uid}/role", response_model=AdminUser, tags=["admin"])
def admin_set_role(uid: str, update: RoleUpdate, _: Account = Depends(require_admin)) -> AdminUser:
    user = app_db.get_user(uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no tiene cuenta.")
    if update.role == "user" and user["role"] == "admin":
        if _is_bootstrap_admin(user["email"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Es administrador inicial (ADMIN_EMAILS): no se le puede quitar el rol.",
            )
        if app_db.count_admins() <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede quitar el último administrador.")
    app_db.set_role(uid, update.role)
    return next(item for item in _admin_users() if item.uid == uid)


@router.get("/admin/users/{uid}/photos", response_model=list[AdminPhoto], tags=["admin"])
def admin_list_photos(uid: str, _: Account = Depends(require_admin)) -> list[AdminPhoto]:
    return [_admin_photo(photo) for photo in app_db.list_photos(uid)]


@router.delete("/admin/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin"])
def admin_delete_photo(photo_id: str, admin: Account = Depends(require_admin)) -> Response:
    photo = app_db.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="photo not found")
    blob_store.delete(photo["object_name"])
    if photo["result_object"]:
        blob_store.delete(photo["result_object"])
    app_db.delete_photo(photo_id)
    logger.info(f"Admin {admin.uid} deleted photo {photo['object_name']}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/admin/users/{uid}/registration", status_code=status.HTTP_204_NO_CONTENT, tags=["admin"])
def admin_delete_registration(uid: str, admin: Account = Depends(require_admin)) -> Response:
    """Borra el registro facial (embeddings y rostros alineados): el usuario tiene que volver a registrarse."""
    deleted = embedding_store.delete_label(uid)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="registration not found")
    # Se borran por nombre exacto los objetos de este registro (los registros previos al bucket no tienen)
    for record in deleted:
        if object_owner(record.path) == uid:
            blob_store.delete(record.path)
    for registration_id in {record.metadata.get("registration_id") for record in deleted} - {None}:
        blob_store.delete(f"registrations/{uid}/{registration_id}/summary.jpg")
        app_db.clear_registration(registration_id)
    logger.info(f"Admin {admin.uid} deleted the face registration of {uid} ({len(deleted)} embeddings)")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
