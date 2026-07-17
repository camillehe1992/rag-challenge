import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response, status

from app.config import Settings, get_settings

SESSION_COOKIE_NAME = "rag_session"
_ACTIVE_SESSIONS: dict[str, float] = {}


def create_session_token(settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    _ACTIVE_SESSIONS[token] = time.time() + float(settings.session_ttl_seconds)
    return token


def validate_credentials(username: str, password: str, settings: Settings) -> bool:
    return (
        secrets.compare_digest(username, settings.demo_username)
        and secrets.compare_digest(password, settings.demo_password)
    )


def _sign_token(token: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest


def _encode_cookie_value(token: str, settings: Settings) -> str:
    signature = _sign_token(token, settings.session_secret)
    return f"{token}.{signature}"


def _decode_cookie_value(cookie_value: str, settings: Settings) -> str | None:
    parts = cookie_value.split(".", 1)
    if len(parts) != 2:
        return None
    token, signature = parts
    expected = _sign_token(token, settings.session_secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=_encode_cookie_value(token, settings),
        httponly=True,
        samesite="lax",
        secure=bool(settings.cookie_secure),
        max_age=int(settings.session_ttl_seconds),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def revoke_session_token(cookie_value: str | None, settings: Settings) -> None:
    if not cookie_value:
        return
    token = _decode_cookie_value(cookie_value, settings)
    if token:
        _ACTIVE_SESSIONS.pop(token, None)


def require_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    token = _decode_cookie_value(session_token, settings)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    expires_at = _ACTIVE_SESSIONS.get(token)
    if not expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if expires_at < time.time():
        _ACTIVE_SESSIONS.pop(token, None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )


def settings_dependency() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dependency)]
AuthDep = Annotated[None, Depends(require_auth)]
