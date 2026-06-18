from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ygo_app.auth import (
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    verify_password,
)
from ygo_app.config import TURNSTILE_SITE_KEY
from ygo_app.database import get_db
from ygo_app.email import send_verification_code
from ygo_app.models import PendingRegistration, User
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

REGISTER_IP_LIMIT = RateLimitSpec(max_count=5, window_seconds=3600)
REGISTER_EMAIL_LIMIT = RateLimitSpec(max_count=3, window_seconds=3600)
RESEND_EMAIL_LIMIT = RateLimitSpec(max_count=3, window_seconds=3600)
VERIFY_IP_LIMIT = RateLimitSpec(max_count=10, window_seconds=3600)
LOGIN_IP_LIMIT = RateLimitSpec(max_count=10, window_seconds=900)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    turnstile_token: str | None = None


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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _queue_verification_email(background_tasks: BackgroundTasks, email: str, code: str) -> None:
    # #region agent log
    from ygo_app.email import _agent_debug_log

    _agent_debug_log(
        "auth.py:_queue_verification_email",
        "background task scheduled",
        {"code_len": len(code)},
        "H2",
    )
    # #endregion
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
    return AuthConfigOut(turnstile_site_key=TURNSTILE_SITE_KEY)


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

    if get_user_by_email(db, email):
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = normalize_email(body.email)
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

    user = get_user_by_email(db, email)
    if user:
        if not user.email_verified_at:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "email_not_verified", "message": "Email not verified"},
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
