from __future__ import annotations

import logging
from typing import Any

from psycopg import connect
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    email TEXT,
    name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES users (uid) ON DELETE CASCADE,
    object_name TEXT NOT NULL UNIQUE,
    content_type TEXT,
    size_bytes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL: subida sin usar; 'registration': foto de un intento de registro; 'prediction': foto predicha
    kind TEXT CHECK (kind IN ('registration', 'prediction')),
    pose TEXT,
    registration_id TEXT,
    result_object TEXT,
    ai_generated BOOLEAN
);
CREATE INDEX IF NOT EXISTS photos_uid_created_idx ON photos (uid, created_at DESC);
"""

_PHOTO_COLUMNS = (
    "id, uid, object_name, content_type, size_bytes, created_at, kind, pose, registration_id, "
    "result_object, ai_generated"
)


class AppDB:
    """Usuarios (con su rol) y catálogo de las fotos guardadas en el bucket, en PostgreSQL."""

    def __init__(self, host: str, port: int, dbname: str, user: str, password: str) -> None:
        self.conn = connect(
            host=host, port=port, dbname=dbname, user=user, password=password,
            autocommit=True, row_factory=dict_row,
        )
        with self.conn.cursor() as cur:
            cur.execute(_SCHEMA)

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # --- usuarios -------------------------------------------------------------------------

    def upsert_user(self, uid: str, email: str | None, name: str | None, bootstrap_admin: bool) -> dict[str, Any]:
        """Crea o actualiza el usuario en cada request; los admins iniciales siempre quedan como admin."""
        return self._one(
            """
            INSERT INTO users (uid, email, name, role)
            VALUES (%(uid)s, %(email)s, %(name)s, CASE WHEN %(admin)s THEN 'admin' ELSE 'user' END)
            ON CONFLICT (uid) DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                last_seen_at = now(),
                role = CASE WHEN %(admin)s THEN 'admin' ELSE users.role END
            RETURNING uid, email, name, role
            """,
            {"uid": uid, "email": email, "name": name, "admin": bootstrap_admin},
        )

    def get_user(self, uid: str) -> dict[str, Any] | None:
        return self._one("SELECT uid, email, name, role, created_at, last_seen_at FROM users WHERE uid = %s", (uid,))

    def list_users(self) -> list[dict[str, Any]]:
        return self._all(
            """
            SELECT u.uid, u.email, u.name, u.role, u.created_at, u.last_seen_at, count(p.id) AS photo_count
            FROM users u LEFT JOIN photos p ON p.uid = u.uid
            GROUP BY u.uid ORDER BY u.created_at
            """
        )

    def set_role(self, uid: str, role: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE uid = %s", (role, uid))

    def count_admins(self) -> int:
        return self._one("SELECT count(*) AS n FROM users WHERE role = 'admin'")["n"]

    # --- fotos ----------------------------------------------------------------------------

    def add_photo(self, photo_id: str, uid: str, object_name: str, content_type: str, size_bytes: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO photos (id, uid, object_name, content_type, size_bytes) VALUES (%s, %s, %s, %s, %s)",
                (photo_id, uid, object_name, content_type, size_bytes),
            )

    def get_photo(self, photo_id: str) -> dict[str, Any] | None:
        return self._one(f"SELECT {_PHOTO_COLUMNS} FROM photos WHERE id = %s", (photo_id,))

    def get_photo_by_object(self, object_name: str) -> dict[str, Any] | None:
        return self._one(f"SELECT {_PHOTO_COLUMNS} FROM photos WHERE object_name = %s", (object_name,))

    def list_photos(self, uid: str) -> list[dict[str, Any]]:
        return self._all(f"SELECT {_PHOTO_COLUMNS} FROM photos WHERE uid = %s ORDER BY created_at DESC", (uid,))

    def mark_registration_attempt(self, poses: dict[str, str]) -> None:
        """poses: pose -> id de foto."""
        with self.conn.cursor() as cur:
            for pose, photo_id in poses.items():
                cur.execute(
                    "UPDATE photos SET kind = 'registration', pose = %s, registration_id = NULL WHERE id = %s",
                    (pose, photo_id),
                )

    def set_registration_id(self, photo_ids: list[str], registration_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("UPDATE photos SET registration_id = %s WHERE id = ANY(%s)", (registration_id, photo_ids))

    def clear_registration(self, registration_id: str) -> None:
        """Las fotos dejan de formar parte del registro vigente (se borró el registro facial)."""
        with self.conn.cursor() as cur:
            cur.execute("UPDATE photos SET registration_id = NULL WHERE registration_id = %s", (registration_id,))

    def set_prediction(self, photo_id: str, result_object: str, ai_generated: bool) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE photos SET kind = 'prediction', pose = NULL, result_object = %s, ai_generated = %s WHERE id = %s",
                (result_object, ai_generated, photo_id),
            )

    def delete_photo(self, photo_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM photos WHERE id = %s", (photo_id,))
