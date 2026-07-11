"""OAuth 2.0 provider integrations (Google, Discord, GitHub, Microsoft)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from authlib.integrations.requests_client import OAuth2Session
from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    MICROSOFT_CLIENT_ID,
    MICROSOFT_CLIENT_SECRET,
    MICROSOFT_TENANT_ID,
    OAUTH_REDIRECT_BASE_URL,
    SECRET_KEY,
)
from ygo_app.models import OAuthIdentity, User
from ygo_app.verification import get_pending_by_email, normalize_email

ALGORITHM = "HS256"
STATE_TTL_MINUTES = 10
EXCHANGE_TTL_SECONDS = 60

SUPPORTED_PROVIDERS = ("google", "discord", "github", "microsoft")


@dataclass(frozen=True)
class OAuthProviderConfig:
    id: str
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str | None
    scope: str
    client_kwargs: dict[str, Any] | None = None


def _provider_configs() -> dict[str, OAuthProviderConfig]:
    configs: dict[str, OAuthProviderConfig] = {}
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        configs["google"] = OAuthProviderConfig(
            id="google",
            name="Google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scope="openid email profile",
        )
    if DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET:
        configs["discord"] = OAuthProviderConfig(
            id="discord",
            name="Discord",
            client_id=DISCORD_CLIENT_ID,
            client_secret=DISCORD_CLIENT_SECRET,
            authorize_url="https://discord.com/api/oauth2/authorize",
            token_url="https://discord.com/api/oauth2/token",
            userinfo_url="https://discord.com/api/users/@me",
            scope="identify email",
        )
    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        configs["github"] = OAuthProviderConfig(
            id="github",
            name="GitHub",
            client_id=GITHUB_CLIENT_ID,
            client_secret=GITHUB_CLIENT_SECRET,
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scope="read:user user:email",
            client_kwargs={"Accept": "application/json"},
        )
    if MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET:
        tenant = MICROSOFT_TENANT_ID or "common"
        base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        configs["microsoft"] = OAuthProviderConfig(
            id="microsoft",
            name="Microsoft",
            client_id=MICROSOFT_CLIENT_ID,
            client_secret=MICROSOFT_CLIENT_SECRET,
            authorize_url=f"{base}/authorize",
            token_url=f"{base}/token",
            userinfo_url="https://graph.microsoft.com/oidc/userinfo",
            scope="openid email profile",
        )
    return configs


def list_enabled_providers() -> list[OAuthProviderConfig]:
    return list(_provider_configs().values())


def get_provider_config(provider: str) -> OAuthProviderConfig:
    config = _provider_configs().get(provider)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "OAuth provider not configured")
    return config


def oauth_callback_url(provider: str) -> str:
    return f"{OAUTH_REDIRECT_BASE_URL}/api/auth/oauth/{provider}/callback"


def oauth_start_url(provider: str) -> str:
    return f"/api/auth/oauth/{provider}/start"


def _encode_token(payload: dict[str, Any], ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    data = {
        **payload,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str, expected_purpose: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth token") from exc
    if payload.get("purpose") != expected_purpose:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth token")
    return payload


def create_oauth_state(provider: str) -> str:
    return _encode_token(
        {"purpose": "oauth_state", "provider": provider},
        timedelta(minutes=STATE_TTL_MINUTES),
    )


def verify_oauth_state(state: str, provider: str) -> None:
    payload = _decode_token(state, "oauth_state")
    if payload.get("provider") != provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state")


def create_oauth_exchange_token(user_id: int) -> str:
    return _encode_token(
        {"purpose": "oauth_exchange", "sub": str(user_id)},
        timedelta(seconds=EXCHANGE_TTL_SECONDS),
    )


def verify_oauth_exchange_token(token: str) -> int:
    payload = _decode_token(token, "oauth_exchange")
    try:
        return int(payload.get("sub", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth token") from exc


def build_authorize_redirect(provider: str, state: str) -> str:
    config = get_provider_config(provider)
    params = {
        "client_id": config.client_id,
        "redirect_uri": oauth_callback_url(provider),
        "response_type": "code",
        "scope": config.scope,
        "state": state,
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    if provider == "github":
        params["allow_signup"] = "true"
    return f"{config.authorize_url}?{urlencode(params)}"


def _build_oauth_client(provider: str) -> OAuth2Session:
    config = get_provider_config(provider)
    return OAuth2Session(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=oauth_callback_url(provider),
        scope=config.scope,
    )


def exchange_code_and_fetch_profile(provider: str, code: str) -> dict[str, Any]:
    config = get_provider_config(provider)
    client = _build_oauth_client(provider)
    token_kwargs: dict[str, Any] = {}
    if config.client_kwargs:
        token_kwargs.update(config.client_kwargs)
    token = client.fetch_token(
        config.token_url,
        code=code,
        grant_type="authorization_code",
        **token_kwargs,
    )
    if provider == "github":
        return _fetch_github_profile(client, token)
    if provider == "discord":
        return _fetch_discord_profile(client, token)
    if provider == "microsoft":
        return _fetch_microsoft_profile(client, token)
    return _fetch_oidc_profile(client, config, token)


def _fetch_oidc_profile(
    client: OAuth2Session,
    config: OAuthProviderConfig,
    token: dict[str, Any],
) -> dict[str, Any]:
    if not config.userinfo_url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OAuth provider misconfigured")
    resp = client.get(config.userinfo_url)
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch OAuth profile")
    data = resp.json()
    email = (data.get("email") or "").strip().lower()
    provider_user_id = str(data.get("sub") or data.get("id") or "")
    if not provider_user_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OAuth provider returned no user id")
    return {
        "provider_user_id": provider_user_id,
        "email": email or None,
        "email_verified": bool(data.get("email_verified", bool(email))),
    }


def _fetch_github_profile(client: OAuth2Session, token: dict[str, Any]) -> dict[str, Any]:
    resp = client.get("https://api.github.com/user")
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch OAuth profile")
    data = resp.json()
    provider_user_id = str(data.get("id") or "")
    email = (data.get("email") or "").strip().lower() or None
    if not email:
        emails_resp = client.get("https://api.github.com/user/emails")
        if emails_resp.status_code < 400:
            for entry in emails_resp.json():
                if entry.get("primary") and entry.get("verified"):
                    email = (entry.get("email") or "").strip().lower() or None
                    break
            if not email:
                for entry in emails_resp.json():
                    if entry.get("verified"):
                        email = (entry.get("email") or "").strip().lower() or None
                        break
    if not provider_user_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OAuth provider returned no user id")
    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "email_verified": bool(email),
    }


def _fetch_discord_profile(client: OAuth2Session, token: dict[str, Any]) -> dict[str, Any]:
    resp = client.get("https://discord.com/api/users/@me")
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch OAuth profile")
    data = resp.json()
    provider_user_id = str(data.get("id") or "")
    email = (data.get("email") or "").strip().lower() or None
    if not provider_user_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OAuth provider returned no user id")
    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "email_verified": bool(data.get("verified", bool(email))),
    }


def _fetch_microsoft_profile(client: OAuth2Session, token: dict[str, Any]) -> dict[str, Any]:
    resp = client.get("https://graph.microsoft.com/oidc/userinfo")
    if resp.status_code >= 400:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch OAuth profile")
    data = resp.json()
    provider_user_id = str(data.get("sub") or "")
    email = (data.get("email") or data.get("preferred_username") or "").strip().lower() or None
    if not provider_user_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OAuth provider returned no user id")
    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "email_verified": bool(data.get("email_verified", bool(email))),
    }


def _get_identity(
    db: Session,
    provider: str,
    provider_user_id: str,
) -> OAuthIdentity | None:
    return db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_user_id == provider_user_id,
        )
    ).scalar_one_or_none()


def resolve_oauth_user(db: Session, provider: str, profile: dict[str, Any]) -> User:
    provider_user_id = profile["provider_user_id"]
    email = profile.get("email")
    email_verified = bool(profile.get("email_verified"))

    if not email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Your account provider did not share an email address. Use email sign-in instead.",
        )
    email = normalize_email(email)

    identity = _get_identity(db, provider, provider_user_id)
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Linked user not found")
        if identity.provider_email != email:
            identity.provider_email = email
            db.commit()
        return user

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.utcnow()

    if user is not None:
        if not email_verified and user.email_verified_at is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Email from provider is not verified. Use email sign-in instead.",
            )
        if user.email_verified_at is None:
            user.email_verified_at = now
        pending = get_pending_by_email(db, email)
        if pending is not None:
            db.delete(pending)
    else:
        pending = get_pending_by_email(db, email)
        if pending is not None:
            db.delete(pending)
        user = User(
            email=email,
            hashed_password=None,
            email_verified_at=now if email_verified else None,
        )
        db.add(user)
        db.flush()

    if user.email_verified_at is None and email_verified:
        user.email_verified_at = now

    db.add(
        OAuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=email,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def oauth_error_redirect(message: str) -> str:
    return f"/#oauth_error={quote(message, safe='')}"


def oauth_success_redirect(exchange_token: str) -> str:
    return f"/#oauth_exchange={quote(exchange_token, safe='')}"
