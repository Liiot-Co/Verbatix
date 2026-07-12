"""Verificación del JWT de Supabase (ES256/RS256 vía JWKS)."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import settings

_jwks_client = PyJWKClient(settings.supabase_jwks_url, cache_keys=True)
_bearer = HTTPBearer(auto_error=True)


class CurrentUser(dict):
    """{'id': <uuid>, 'email': <str>}"""


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
