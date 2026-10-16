from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from dotenv import load_dotenv
import logging
import os
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # Una variable vacía cuenta como no definida: docker-compose pasa vacías las que no se exportaron
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True)

    cors_origins: str = Field(
        default="*",
        description="Comma-separated allowed origins, or * for any.",
    )
    app_name: str = "Facial Recognition TP1"
    model_name: str | None = os.getenv("MODEL_NAME")
    similarity_metric: str = os.getenv("SIMILARITY_METRIC", "cosine")
    similarity_threshold: float = os.getenv("SIMILARITY_THRESHOLD", 0.55)
    embeddings_path: Path = Path(os.getenv("EMBEDDINGS_PATH", "data/embeddings.json"))
    data_path: Path = Path(os.getenv("DATA_PATH", "data"))
    output_path: Path = Path(os.getenv("OUTPUT_PATH", "output"))
    model_path: Path = Path(os.getenv("MODEL_PATH", "lib/models"))
    detector_model_name: str = os.getenv("DETECTOR_MODEL_NAME", "scrfd_10g_bnkps.onnx")
    det_score_threshold: float = os.getenv("DET_SCORE_THRESHOLD", 0.5)
    det_input_size: int = os.getenv("DET_INPUT_SIZE", 640)
    min_face_size: int = os.getenv("MIN_FACE_SIZE", 20)
    align_margin: float = os.getenv("ALIGN_MARGIN", 0.5)
    # Validación del registro (4 fotos): pose con landmarks 3D y tamaño relativo del rostro
    pose_model_name: str = os.getenv("POSE_MODEL_NAME", "1k3d68.onnx")
    frontal_max_yaw: float = os.getenv("FRONTAL_MAX_YAW", 20)
    profile_min_yaw: float = os.getenv("PROFILE_MIN_YAW", 45)
    close_far_min_ratio: float = os.getenv("CLOSE_FAR_MIN_RATIO", 1.3)
    registration_min_similarity: float = os.getenv("REGISTRATION_MIN_SIMILARITY", 0.3)
    # Detección de imágenes generadas/alteradas con IA (metadatos + clasificador Community Forensics)
    ai_detector_model_name: str = os.getenv("AI_DETECTOR_MODEL_NAME", "community_forensics_vit_s384.onnx")
    ai_detection_threshold: float = os.getenv("AI_DETECTION_THRESHOLD", 0.9)
    max_workers: int = os.getenv("MAX_WORKERS", 2)
    face_size: int = os.getenv("FACE_SIZE", 112)
    embedding_dim: int = os.getenv("EMBEDDING_DIM", 512)
    # Valores propios de cada despliegue: se exportan en la shell o en ./.env (ver .env.example y README)
    # Proyecto de Google Cloud (Firebase Auth y GCS)
    gcp_project_id: str | None = os.getenv("GCP_PROJECT_ID") or None
    # Proyecto de Firebase cuyos ID tokens acepta el backend: por defecto GCP_PROJECT_ID (otro para el emulador)
    firebase_project_id: str | None = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GCP_PROJECT_ID") or None
    # Emails (verificados) que siempre son administradores, separados por coma
    admin_emails: str = os.getenv("ADMIN_EMAILS", "")
    # Almacenamiento de imágenes: "gcs" (bucket) o "local" (carpeta OUTPUT_PATH, para desarrollo sin GCP)
    storage_backend: str = os.getenv("STORAGE_BACKEND", "gcs")
    gcs_bucket: str | None = os.getenv("GCS_BUCKET") or None
    # Service account a impersonar con las credenciales por defecto (vacío: usar ADC directamente)
    gcs_service_account: str | None = os.getenv("GCS_SERVICE_ACCOUNT") or None
    # Prefijo para todos los objetos (permite aislar entornos dentro del mismo bucket)
    storage_prefix: str = os.getenv("STORAGE_PREFIX", "")
    max_upload_mb: float = os.getenv("MAX_UPLOAD_MB", 15)
    use_pgvector: bool = os.getenv("USE_PGVECTOR", "True").lower() == "true"
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = os.getenv("POSTGRES_PORT", 5432)
    postgres_db: str = os.getenv("POSTGRES_DB", "vector_db")
    postgres_user: str = os.getenv("POSTGRES_USER", "user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "password")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
