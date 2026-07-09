from urllib.parse import urlencode
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connected_apps.google_oauth import (
    exchange_google_code,
    google_login_provider_keys,
    google_login_scopes,
    store_google_oauth_accounts,
)
from app.core_domain.service import ensure_default_workspace
from app.db.session import get_db
from app.models import User
from app.schemas import (
    AuthResponse,
    GoogleConfigResponse,
    GoogleCredentialRequest,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.security import (
    OAUTH_STATE_COOKIE,
    clear_session_cookie,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        avatar_url=user.avatar_url,
        google_connected=bool(user.google_sub),
        created_at=user.created_at,
    )


def verify_google_identity(raw_id_token: str) -> dict:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google sign-in is not configured")

    try:
        id_info = id_token.verify_oauth2_token(
            raw_id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google identity") from exc

    if id_info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google issuer")

    if id_info.get("email_verified") not in {True, "true", "True", "1", 1}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google email is not verified")

    return id_info


def upsert_google_user(id_info: dict, db: Session) -> User:
    google_sub = id_info.get("sub")
    email = (id_info.get("email") or "").lower()
    if not google_sub or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google profile is missing email")

    user = db.scalar(select(User).where(User.google_sub == google_sub))
    if not user:
        user = db.scalar(select(User).where(User.email == email))

    if user:
        user.google_sub = user.google_sub or google_sub
        user.avatar_url = user.avatar_url or id_info.get("picture")
        user.first_name = user.first_name or id_info.get("given_name")
        user.last_name = user.last_name or id_info.get("family_name")
    else:
        user = User(
            email=email,
            google_sub=google_sub,
            first_name=id_info.get("given_name"),
            last_name=id_info.get("family_name"),
            avatar_url=id_info.get("picture"),
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    ensure_default_workspace(db, user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_default_workspace(db, user)
    db.commit()
    set_session_cookie(response, user.id)
    return AuthResponse(user=serialize_user(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    ensure_default_workspace(db, user)
    db.commit()
    set_session_cookie(response, user.id)
    return AuthResponse(user=serialize_user(user))


@router.get("/me", response_model=AuthResponse)
def me(user: User = Depends(get_current_user)) -> AuthResponse:
    return AuthResponse(user=serialize_user(user))


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/google/config", response_model=GoogleConfigResponse)
def google_config() -> GoogleConfigResponse:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google sign-in is not configured")
    return GoogleConfigResponse(client_id=settings.google_client_id)


@router.post("/google", response_model=AuthResponse)
def google_token_login(
    payload: GoogleCredentialRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthResponse:
    user = upsert_google_user(verify_google_identity(payload.credential), db)
    set_session_cookie(response, user.id)
    return AuthResponse(user=serialize_user(user))


@router.get("/google/start")
def google_start() -> RedirectResponse:
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth is not configured")

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(google_login_scopes()),
        "access_type": "offline",
        "prompt": "consent select_account",
        "state": state,
    }
    response = RedirectResponse(f"{settings.google_auth_uri}?{urlencode(params)}")
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=10 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = get_settings()
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    token_data = await exchange_google_code(code=code, redirect_uri=settings.google_redirect_uri)
    raw_id_token = token_data.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google did not return an ID token")

    user = upsert_google_user(verify_google_identity(raw_id_token), db)
    await store_google_oauth_accounts(
        db,
        user=user,
        token_data=token_data,
        provider_keys=google_login_provider_keys(),
    )
    db.commit()

    response = RedirectResponse(f"{str(settings.frontend_url).rstrip('/')}/dashboard")
    set_session_cookie(response, user.id)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/", samesite="lax")
    return response
