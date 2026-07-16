from typing import Annotated

from pathlib import Path

from fastapi import Cookie, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import (
    AuthDep,
    SESSION_COOKIE_NAME,
    SettingsDep,
    clear_session_cookie,
    create_session_token,
    revoke_session_token,
    set_session_cookie,
    validate_credentials,
)
from app.rag.pipeline import answer_question
from app.schemas import ChatRequest, ChatResponse, LoginRequest, LoginResponse

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="THSS RAG Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "https://localhost:8443"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_probe() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/health")
def health(settings: SettingsDep) -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.post("/api/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    settings: SettingsDep,
) -> LoginResponse:
    if not validate_credentials(payload.username, payload.password, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_session_token(settings)
    set_session_cookie(response, token)
    return LoginResponse(ok=True, username=payload.username)


@app.post("/api/logout")
def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict[str, bool]:
    revoke_session_token(session_token)
    clear_session_cookie(response)
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, _: AuthDep) -> ChatResponse:
    return answer_question(payload.message, payload.history)
