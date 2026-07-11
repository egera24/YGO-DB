import json
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from ygo_app.auth import (
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    validate_password_strength,
    verify_password,
)
from ygo_app.config import TURNSTILE_SITE_KEY
from ygo_app.database import get_db
from ygo_app.email import send_verification_code
from ygo_app.models import PendingRegistration, User
from ygo_app.oauth import (
    SUPPORTED_PROVIDERS,
    build_authorize_redirect,
    create_oauth_exchange_token,
    create_oauth_state,
    exchange_code_and_fetch_profile,
    list_enabled_providers,
    oauth_error_redirect,
    oauth_start_url,
    oauth_success_redirect,
    resolve_oauth_user,
    verify_oauth_exchange_token,
    verify_oauth_state,
)
from ygo_app.rate_limit import RateLimitSpec, enforce_rate_limit
from ygo_app.turnstile import turnstile_required, verify_turnstile_token
from ygo_app.verification import (
    MAX_OTP_ATTEMPTS,
    cleanup_stale_pending,
    get_pending_by_email,
    issue_otp_for_pending,
    is_otp_expired,
    normalize_email,
    verify_otp,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_DEBUG_LOG = Path(__file__).resolve().parent.parent.parent.parent / "debug-3b87b6.log"


def _agent_log(location: str, message: str, data: dict, hypothesis_id: str, run_id: str = "pre-fix") -> None:
    # #region agent log
    try:
        with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "sessionId": "3b87b6",
                        "runId": run_id,
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

REGISTER_IP_LIMIT = RateLimitSpec(max_count=5, window_seconds=3600)
REGISTER_EMAIL_LIMIT = RateLimitSpec(max_count=3, window_seconds=3600)
RESEND_EMAIL_LIMIT = RateLimitSpec(max_count=3, window_seconds=3600)
RESEND_IP_LIMIT = RateLimitSpec(max_count=10, window_seconds=3600)
VERIFY_IP_LIMIT = RateLimitSpec(max_count=10, window_seconds=3600)
LOGIN_IP_LIMIT = RateLimitSpec(max_count=10, window_seconds=900)
LOGIN_EMAIL_LIMIT = RateLimitSpec(max_count=10, window_seconds=900)
OAUTH_START_IP_LIMIT = RateLimitSpec(max_count=20, window_seconds=900)
OAUTH_COMPLETE_IP_LIMIT = RateLimitSpec(max_count=20, window_seconds=900)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    turnstile_token: str | None = None

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendCodeIn(BaseModel):
    email: EmailStr


class NeedsVerificationOut(BaseModel):
    needs_verification: bool = True
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    email_verified: bool

    model_config = {"from_attributes": True}


class AuthConfigOut(BaseModel):
    turnstile_site_key: str | None = None
    oauth_providers: list["OAuthProviderOut"] = []


class OAuthProviderOut(BaseModel):
    id: str
    name: str
    start_url: str


class OAuthCompleteIn(BaseModel):
    exchange_token: str = Field(min_length=10)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _queue_verification_email(background_tasks: BackgroundTasks, email: str, code: str) -> None:
    background_tasks.add_task(send_verification_code, email, code)


def _start_pending_registration(
    db: Session,
    background_tasks: BackgroundTasks,
    email: str,
    password: str,
) -> NeedsVerificationOut:
    cleanup_stale_pending(db)
    pending = get_pending_by_email(db, email)
    if pending is None:
        pending = PendingRegistration(
            email=email,
            hashed_password=hash_password(password),
            otp_hash="",
            otp_expires_at=datetime.utcnow(),
        )
        db.add(pending)
    else:
        pending.hashed_password = hash_password(password)

    code = issue_otp_for_pending(pending)
    db.commit()
    _queue_verification_email(background_tasks, email, code)
    return NeedsVerificationOut(email=email)


@router.get("/config", response_model=AuthConfigOut)
def auth_config():
    oauth_providers = [
        OAuthProviderOut(
            id=provider.id,
            name=provider.name,
            start_url=oauth_start_url(provider.id),
        )
        for provider in list_enabled_providers()
    ]
    return AuthConfigOut(
        turnstile_site_key=TURNSTILE_SITE_KEY,
        oauth_providers=oauth_providers,
    )


@router.post("/register", response_model=NeedsVerificationOut, status_code=status.HTTP_200_OK)
def register(
    body: RegisterIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = normalize_email(body.email)
    client_ip = _client_ip(request)

    enforce_rate_limit(db, f"register:ip:{client_ip}", REGISTER_IP_LIMIT)
    enforce_rate_limit(db, f"register:email:{email}", REGISTER_EMAIL_LIMIT)

    if turnstile_required() and not verify_turnstile_token(body.turnstile_token, client_ip):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Captcha verification failed")

    existing = get_user_by_email(db, email)
    if existing:
        if existing.hashed_password is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This email uses social sign-in. Continue with Google, Discord, GitHub, or Microsoft.",
            )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    return _start_pending_registration(db, background_tasks, email, body.password)


@router.post("/verify-email", response_model=TokenOut)
def verify_email(body: VerifyEmailIn, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    client_ip = _client_ip(request)
    enforce_rate_limit(db, f"verify:ip:{client_ip}", VERIFY_IP_LIMIT)

    pending = get_pending_by_email(db, email)
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification code")

    if is_otp_expired(pending.otp_expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Verification code expired. Request a new one.")

    if pending.otp_attempts >= MAX_OTP_ATTEMPTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Too many failed attempts. Request a new verification code.",
        )

    if not verify_otp(body.code, pending.otp_hash):
        pending.otp_attempts += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification code")

    if get_user_by_email(db, email):
        db.delete(pending)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    now = datetime.utcnow()
    user = User(
        email=email,
        hashed_password=pending.hashed_password,
        email_verified_at=now,
    )
    db.add(user)
    db.delete(pending)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/resend-code", status_code=status.HTTP_200_OK)
def resend_code(
    body: ResendCodeIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = normalize_email(body.email)
    client_ip = _client_ip(request)
    enforce_rate_limit(db, f"resend:ip:{client_ip}", RESEND_IP_LIMIT)
    enforce_rate_limit(db, f"resend:email:{email}", RESEND_EMAIL_LIMIT)

    pending = get_pending_by_email(db, email)
    if pending is not None:
        code = issue_otp_for_pending(pending)
        db.commit()
        _queue_verification_email(background_tasks, email, code)

    return {"message": "If an account is pending verification, we sent a new code."}


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = normalize_email(body.email)
    client_ip = _client_ip(request)
    enforce_rate_limit(db, f"login:ip:{client_ip}", LOGIN_IP_LIMIT)
    enforce_rate_limit(db, f"login:email:{email}", LOGIN_EMAIL_LIMIT)

    user = get_user_by_email(db, email)
    if user:
        if not user.email_verified_at:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "email_not_verified", "message": "Email not verified"},
            )
        if user.hashed_password is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This account uses social sign-in. Continue with Google, Discord, GitHub, or Microsoft.",
            )
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
        return TokenOut(access_token=create_access_token(user.id))

    pending = get_pending_by_email(db, email)
    if pending and verify_password(body.password, pending.hashed_password):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "email_not_verified", "message": "Email not verified"},
        )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
    )


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str, request: Request, db: Session = Depends(get_db)):
    # #region agent log
    _agent_log(
        "auth.py:oauth_start",
        "oauth_start_entry",
        {"provider": provider},
        "B",
    )
    # #endregion
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OAuth provider not supported")
    client_ip = _client_ip(request)
    try:
        enforce_rate_limit(db, f"oauth_start:ip:{client_ip}", OAUTH_START_IP_LIMIT)
        # #region agent log
        _agent_log("auth.py:oauth_start", "after_rate_limit", {"client_ip": client_ip}, "A")
        # #endregion
        db.commit()
        # #region agent log
        _agent_log("auth.py:oauth_start", "after_commit", {}, "D")
        # #endregion
        state = create_oauth_state(provider)
        # #region agent log
        _agent_log("auth.py:oauth_start", "after_state_token", {"state_len": len(state)}, "E")
        # #endregion
        redirect_url = build_authorize_redirect(provider, state)
        # #region agent log
        _agent_log(
            "auth.py:oauth_start",
            "redirect_ready",
            {"redirect_host": redirect_url.split("/")[2] if "://" in redirect_url else "unknown"},
            "B",
        )
        # #endregion
        return RedirectResponse(redirect_url, status_code=status.HTTP_302_FOUND)
    except HTTPException:
        raise
    except Exception as exc:
        # #region agent log
        _agent_log(
            "auth.py:oauth_start",
            "oauth_start_failed",
            {"error_type": type(exc).__name__, "error": str(exc)[:500]},
            "C",
        )
        # #endregion
        raise


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if provider not in SUPPORTED_PROVIDERS:
        return RedirectResponse(oauth_error_redirect("OAuth provider not supported"))
    if error:
        return RedirectResponse(oauth_error_redirect("Sign-in was cancelled or denied."))
    if not code or not state:
        return RedirectResponse(oauth_error_redirect("Missing OAuth response."))
    try:
        verify_oauth_state(state, provider)
        profile = exchange_code_and_fetch_profile(provider, code)
        user = resolve_oauth_user(db, provider, profile)
        exchange_token = create_oauth_exchange_token(user.id)
        return RedirectResponse(oauth_success_redirect(exchange_token), status_code=status.HTTP_302_FOUND)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "OAuth sign-in failed."
        return RedirectResponse(oauth_error_redirect(detail))
    except Exception:
        return RedirectResponse(oauth_error_redirect("OAuth sign-in failed. Please try again."))


@router.post("/oauth/complete", response_model=TokenOut)
def oauth_complete(body: OAuthCompleteIn, request: Request, db: Session = Depends(get_db)):
    client_ip = _client_ip(request)
    enforce_rate_limit(db, f"oauth_complete:ip:{client_ip}", OAUTH_COMPLETE_IP_LIMIT)
    db.commit()
    user_id = verify_oauth_exchange_token(body.exchange_token)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return TokenOut(access_token=create_access_token(user.id))
