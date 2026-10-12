"""Validate SPACE JWTs. Identity is taken from the token only — never from the body."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from jose import JWTError, jwt

from app.core.config import settings

SPACE_NAME_ID = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"


def decode_space_token(token: str) -> Optional[dict[str, Any]]:
    key = (settings.SPACE_JWT_KEY or "").strip()
    if not key or not token.strip():
        return None
    try:
        return jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=settings.SPACE_JWT_AUDIENCE,
            issuer=settings.SPACE_JWT_ISSUER,
        )
    except JWTError:
        return None


def space_user_id(payload: dict[str, Any]) -> str:
    for key in (SPACE_NAME_ID, "nameid", "sub", "userId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int):
            return str(value)
    return ""


def hash_user_id(user_id: str) -> str:
    if not user_id:
        return "anonymous"
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
