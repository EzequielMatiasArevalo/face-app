from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class EmbeddingRecord(BaseModel):
    id_imagen: str
    embedding: list[float]
    path: str
    etiqueta: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegistrationImages(BaseModel):
    """Rutas (devueltas por /upload) de las 4 fotos requeridas para registrar una identidad."""

    front_close: str = Field(description="Foto frontal de cerca.")
    front_far: str = Field(description="Foto frontal más lejos (rostro más chico que en front_close).")
    profile_left: str = Field(description="Foto de perfil de un lado.")
    profile_right: str = Field(description="Foto de perfil del lado opuesto.")


class InsertRequest(BaseModel):
    """La identidad es el uid del usuario autenticado (no se envía en el body)."""

    images: RegistrationImages
    metadata: dict[str, Any] = Field(default_factory=dict)


Role = Literal["user", "admin"]


class MeResponse(BaseModel):
    uid: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: Role
    face_registered: bool


class AdminUser(BaseModel):
    uid: str = Field(description="uid de Firebase, o la etiqueta de una identidad registrada sin cuenta.")
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[Role] = Field(default=None, description="null si la identidad no tiene cuenta.")
    has_account: bool
    bootstrap_admin: bool = Field(description="Admin definido en ADMIN_EMAILS: no se le puede quitar el rol.")
    face_registered: bool
    photo_count: int
    last_seen_at: Optional[datetime] = None


class AdminPhoto(BaseModel):
    id: str
    uid: str
    url: str = Field(description="URL relativa al API de la imagen (/files/...).")
    created_at: datetime
    kind: Optional[Literal["registration", "prediction"]] = None
    pose: Optional[str] = None
    active_registration: bool = Field(default=False, description="Forma parte del registro facial vigente.")
    result_url: Optional[str] = None
    ai_generated: Optional[bool] = None
    size_bytes: Optional[int] = None


class RoleUpdate(BaseModel):
    role: Role


class AlignedFace(BaseModel):
    """One aligned face from insightface (bbox/kps/image may be numpy arrays)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    bbox: Any
    keypoints: Any
    image: Any
    embedding: Optional[list[float]] = None


class PredictRequest(BaseModel):
    source_path: str
    source_type: Literal["image", "video"] = "image"


class AsyncTaskCreated(BaseModel):
    status: Literal["accepted"] = "accepted"
    job_id: str


class UploadResponse(BaseModel):
    """Respuesta tras subir un archivo al servidor (rutas usadas por /predict y /insert)."""

    path: str
    download_url: str


class StatusResponse(BaseModel):
    status: Literal["done", "inProgress", "failed"]
    link: str
    reason: Optional[str] = None
    artifact_url: Optional[str] = Field(
        default=None,
        description="URL relativa al API del artefacto principal (.json o imagen de registro).",
    )
    source_image_url: Optional[str] = Field(
        default=None,
        description="URL relativa de la imagen origen (predicción con resultado JSON).",
    )

class FaceDetection(BaseModel):
    bbox: list[int]
    keypoints: dict[str, list[int]]
    label: str
    name: str = Field(description="Nombre para mostrar de la identidad (o el label si no tiene).")
    score: float


class AIDetection(BaseModel):
    """Resultado de validar si una imagen fue generada o alterada con IA."""

    is_ai_generated: bool
    method: Literal["metadata", "model"] = Field(
        description="metadata: marcas de procedencia (C2PA/IPTC, Stable Diffusion, ComfyUI); model: clasificador."
    )
    score: Optional[float] = Field(default=None, description="Probabilidad de IA según el modelo (null si decidieron los metadatos).")
    evidence: str


class PredictResult(BaseModel):
    source_path: str
    ai_detection: AIDetection
    detections: list[FaceDetection] = Field(description="Vacío si la imagen es generada con IA (no se corre la detección).")
    detected_people: list[str]
