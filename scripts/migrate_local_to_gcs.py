"""
Migra al bucket las imágenes que el backend guardaba en output/ antes de usar GCS.

  - output/uploads/<uid>/up_<id>.<ext>   -> uploads/<uid>/<id>.<ext>        (+ fila en photos, sin clasificar)
  - output/result-*.json                 -> results/<uid>/<id>.json          (marca la foto como predicción)
  - output/img_<rid>_<pose>.jpg          -> registrations/<uid>/<rid>/<pose>.jpg  (actualiza embeddings.path)
  - output/img_<rid>.jpg                 -> registrations/<uid>/<rid>/summary.jpg

No borra ni modifica los archivos locales y nunca sobrescribe objetos existentes. Uso (desde la raíz):

  docker compose run --rm --no-deps --entrypoint python -v "$PWD/scripts:/scripts:ro" \\
      backend -I /scripts/migrate_local_to_gcs.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from google.api_core.exceptions import PreconditionFailed  # noqa: E402
from psycopg import connect  # noqa: E402

from lib.config import settings  # noqa: E402
from lib.storage.app_db import AppDB  # noqa: E402
from lib.storage.blob_store import GCSBlobStore  # noqa: E402

UPLOAD_RE = re.compile(r"^up_([0-9a-f]{32})(\.[a-z]+)$")
RESULT_SOURCE_RE = re.compile(r"/uploads/([A-Za-z0-9_-]+)/up_([0-9a-f]{32})(\.[a-z]+)$")
CROP_RE = re.compile(r"^(?:.*/)?img_([0-9a-f-]{36})_(front_close|front_far|profile_left|profile_right)\.jpg$")
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/app/output", help="carpeta output/ local")
    parser.add_argument("--dry-run", action="store_true", help="solo mostrar qué se haría")
    args = parser.parse_args()
    output = Path(args.output)
    dry = args.dry_run

    store = GCSBlobStore(settings.gcs_bucket, settings.gcp_project_id, settings.gcs_service_account, settings.storage_prefix)
    db = AppDB(settings.postgres_host, settings.postgres_port, settings.postgres_db, settings.postgres_user, settings.postgres_password)
    raw = connect(
        host=settings.postgres_host, port=settings.postgres_port, dbname=settings.postgres_db,
        user=settings.postgres_user, password=settings.postgres_password, autocommit=True,
    )
    stats = {"uploaded": 0, "already_in_bucket": 0, "skipped": 0}

    def upload(object_name: str, data: bytes, content_type: str) -> None:
        print(f"  {'[dry-run] ' if dry else ''}subir gs://{settings.gcs_bucket}/{settings.storage_prefix}{object_name}")
        if dry:
            return
        try:
            store.bucket.blob(store.prefix + object_name).upload_from_string(
                data, content_type=content_type, if_generation_match=0
            )
            stats["uploaded"] += 1
        except PreconditionFailed:
            print("    ya existe en el bucket: no se sobrescribe")
            stats["already_in_bucket"] += 1

    # Datos de cada identidad (nombre y email) desde sus embeddings, para crear su fila en users
    with raw.cursor() as cur:
        cur.execute("SELECT id_imagen, etiqueta, path, metadata FROM embeddings")
        embeddings = cur.fetchall()
    identities = {row[1]: row[3] for row in embeddings}

    def ensure_user(uid: str) -> None:
        if db.get_user(uid) is None:
            meta = identities.get(uid, {})
            print(f"  {'[dry-run] ' if dry else ''}crear usuario {uid} ({meta.get('display_name')}, rol user)")
            if not dry:
                db.upsert_user(uid, meta.get("email"), meta.get("display_name"), bootstrap_admin=False)

    print("== Fotos subidas")
    uploads_dir = output / "uploads"
    for user_dir in sorted(p for p in uploads_dir.iterdir() if p.is_dir()) if uploads_dir.exists() else []:
        uid = user_dir.name
        ensure_user(uid)
        for path in sorted(user_dir.iterdir()):
            match = UPLOAD_RE.match(path.name)
            if not match:
                print(f"  omitido (nombre inesperado): {path}")
                stats["skipped"] += 1
                continue
            photo_id, ext = match.groups()
            object_name = f"uploads/{uid}/{photo_id}{ext}"
            upload(object_name, path.read_bytes(), CONTENT_TYPES.get(ext, "application/octet-stream"))
            if not dry and db.get_photo(photo_id) is None:
                db.add_photo(photo_id, uid, object_name, CONTENT_TYPES.get(ext, "application/octet-stream"), path.stat().st_size)
                with raw.cursor() as cur:
                    cur.execute(
                        "UPDATE photos SET created_at = %s WHERE id = %s",
                        (datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc), photo_id),
                    )

    print("== Resultados de predicción")
    # Del más nuevo al más viejo: si una foto se predijo varias veces queda el último resultado
    for path in sorted(output.glob("result-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        payload = json.loads(path.read_text(encoding="utf-8"))
        match = RESULT_SOURCE_RE.search(payload.get("source_path", ""))
        if not match:
            print(f"  omitido (sin uid, previo al login): {path.name} -> {payload.get('source_path')}")
            stats["skipped"] += 1
            continue
        uid, photo_id, ext = match.groups()
        payload["source_path"] = f"uploads/{uid}/{photo_id}{ext}"
        result_object = f"results/{uid}/{photo_id}.json"
        upload(result_object, json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8"), "application/json")
        ai = payload.get("ai_detection")
        photo = None if dry else db.get_photo(photo_id)
        if photo is not None and photo["result_object"] is None:
            db.set_prediction(photo_id, result_object, ai["is_ai_generated"] if ai else None)

    print("== Rostros alineados de los registros")
    summaries: set[tuple[str, str]] = set()
    for id_imagen, uid, old_path, meta in embeddings:
        match = CROP_RE.match(old_path)
        local = output / Path(old_path).name
        if not match or not local.exists():
            print(f"  omitido: embedding de '{uid}' con path {old_path} (archivo local inexistente o sin formato)")
            stats["skipped"] += 1
            continue
        registration_id, pose = match.groups()
        object_name = f"registrations/{uid}/{registration_id}/{pose}.jpg"
        upload(object_name, local.read_bytes(), "image/jpeg")
        print(f"  {'[dry-run] ' if dry else ''}embeddings.path {id_imagen}: {old_path} -> {object_name}")
        if not dry:
            with raw.cursor() as cur:
                cur.execute("UPDATE embeddings SET path = %s WHERE id_imagen = %s", (object_name, id_imagen))
        summaries.add((uid, registration_id))
    for uid, registration_id in sorted(summaries):
        local = output / f"img_{registration_id}.jpg"
        if local.exists():
            upload(f"registrations/{uid}/{registration_id}/summary.jpg", local.read_bytes(), "image/jpeg")

    print(f"== Resumen: {stats}")


if __name__ == "__main__":
    main()
