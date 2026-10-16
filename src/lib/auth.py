from __future__ import annotations

import logging
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from google.auth.credentials import AnonymousCredentials

from lib.config import settings

logger = logging.getLogger(__name__)


class _PublicKeysOnly(credentials.Base):
    """
    Verificar un ID token de Firebase solo requiere los certificados públicos de Google,
    así que no hace falta una service account (firebase-admin la pide igual al inicializar).
    """

    def get_credential(self):
        return AnonymousCredentials()


if not settings.firebase_project_id:
    raise ValueError("FIREBASE_PROJECT_ID is required to verify Firebase ID tokens")

_firebase_app = firebase_admin.initialize_app(
    _PublicKeysOnly(),
    options={"projectId": settings.firebase_project_id},
    name="auth",
)
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    uid: str
    email: str | None
    name: str | None
    email_verified: bool


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Dependencia de FastAPI: exige `Authorization: Bearer <Firebase ID token>`."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de Firebase (Authorization: Bearer <idToken>).",
        )
    try:
        claims = auth.verify_id_token(creds.credentials, app=_firebase_app)
    except auth.CertificateFetchError as exc:
        logger.exception("Could not fetch Firebase public keys")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (auth.InvalidIdTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Token de Firebase inválido: {exc}"
        ) from exc
    return CurrentUser(
        uid=claims["uid"],
        email=claims.get("email"),
        name=claims.get("name"),
        email_verified=bool(claims.get("email_verified", False)),
    )
