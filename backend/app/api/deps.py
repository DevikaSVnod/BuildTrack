from __future__ import annotations

import time
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, make_transient

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

security = HTTPBearer()

# Avoid an Azure SQL round-trip on every authenticated page API call.
_USER_TTL_S = 90.0
_user_by_token: dict[str, tuple[float, User]] = {}
_user_lock = Lock()


def _cached_user(token: str) -> Optional[User]:
    entry = _user_by_token.get(token)
    if entry is None:
        return None
    ts, user = entry
    if time.time() - ts > _USER_TTL_S:
        with _user_lock:
            _user_by_token.pop(token, None)
        return None
    return user


def _store_user(token: str, user: User) -> User:
    # Detach so the object stays usable after the request session closes.
    make_transient(user)
    with _user_lock:
        _user_by_token[token] = (time.time(), user)
        if len(_user_by_token) > 200:
            oldest = sorted(_user_by_token.items(), key=lambda x: x[1][0])[:50]
            for key, _ in oldest:
                _user_by_token.pop(key, None)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    cached = _cached_user(token)
    if cached is not None:
        return cached

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return _store_user(token, user)
