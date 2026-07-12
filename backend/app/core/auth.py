"""Verificación del JWT de Supabase (ES256/RS256 vía JWKS) — o, en app_mode=local,
un usuario fijo sin llamadas a Supabase (ver Settings.app_mode)."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import settings


class CurrentUser(dict):
    """{'id': <uuid>, 'email': <str>}"""


if settings.app_mode == "local":

    def current_user() -> CurrentUser:
        return CurrentUser({"id": settings.local_dev_user_id, "email": settings.local_dev_user_email})

else:
    _jwks_client = PyJWKClient(settings.supabase_jwks_url, cache_keys=True)
    _bearer = HTTPBearer(auto_error=True)

    def current_user(
        cred: HTTPAuthorizationCredentials = Depends(_bearer),
    ) -> CurrentUser:
        token = cred.credentials
        try:
            signing_key = _jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token inválido: {exc}",
            ) from exc

        return CurrentUser({"id": claims["sub"], "email": claims.get("email")})
