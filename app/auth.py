import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status

from app.config import Settings, get_settings

SESSION_COOKIE_NAME = "rag_session"
_ACTIVE_SESSIONS: set[str] = set()


def create_session_token(settings: Settings) -> str:
    _ = settings
    token = secrets.token_urlsafe(32)
    _ACTIVE_SESSIONS.add(token)
    return token


def validate_credentials(username: str, password: str, settings: Settings) -> bool:
    return (
        secrets.compare_digest(username, settings.demo_username)
        and secrets.compare_digest(password, settings.demo_password)
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 8,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME)


def revoke_session_token(token: str | None) -> None:
    if token:
        _ACTIVE_SESSIONS.discard(token)


def require_auth(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    if not session_token or session_token not in _ACTIVE_SESSIONS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )


def settings_dependency() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]
AuthDep = Annotated[None, Depends(require_auth)]
