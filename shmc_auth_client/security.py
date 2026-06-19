"""=== Module: shmc_auth_client.security ========================================================
Reusable FastAPI JWT authentication dependencies for SHMC subprojects.

=== Purpose ===
This module contains only JWT bearer-token authentication and claim-level Auth Admin
checks. It has no Auth DB, no API-key DB, no password, and no registration logic.

=================================================================================== by Sziller & GPT-5 ==="""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from shmc_auth_client.auth_code import AUTH_BIT_ADMIN, is_auth_admin
from shmc_auth_client.jwt_service import JWTService, jwt_error_message


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", scheme_name="browserAuth")


def extract_bearer_token(authorization: str | None) -> str:
    """=== Function: extract_bearer_token ============================================================
    Parse an HTTP Authorization header and return the bearer token part.

    === Expected Input ===
        Authorization: Bearer <TOKEN>

    === Failure Behavior ===
    Raises HTTP 401 for missing or malformed bearer headers.

    =================================================================================== by Sziller & GPT-5 ==="""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, sep, token = authorization.partition(" ")
    if not sep or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def verify_token_from_authorization_header(jwt_service: JWTService, authorization: str | None) -> dict[str, Any]:
    """=== Function: verify_token_from_authorization_header =========================================
    Verify a raw Authorization header using an explicit JWTService instance.

    === Purpose ===
    This variant is useful for non-FastAPI code paths or tests that already own a
    configured JWTService.

    =================================================================================== by Sziller & GPT-5 ==="""
    token = extract_bearer_token(authorization)
    try:
        return jwt_service.verify_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=jwt_error_message(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_auth_admin_claims(claims: dict[str, Any]) -> None:
    """=== Function: require_auth_admin_claims =======================================================
    Enforce SHMC Auth Admin authorization on already verified claims.

    === Required Authorization State ===
      - auth_code has admin bit set at position 5, value 32
      - "AUTH" is present in projects

    === Failure Behavior ===
    Raises HTTP 403 when claims are valid but not sufficient for Auth Admin actions.

    =================================================================================== by Sziller & GPT-5 ==="""
    auth_code = int(claims.get("auth_code") or claims.get("auth_level") or 0)
    projects = {str(project).strip().upper() for project in (claims.get("projects") or [])}
    if not is_auth_admin(auth_code) or "AUTH" not in projects:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"AUTH admin privileges required: auth_code bit {AUTH_BIT_ADMIN} and AUTH project access.",
        )


async def get_current_claims(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    """=== Function: get_current_claims ================================================================
    FastAPI dependency that authenticates a request using an SHMC JWT bearer token.

    === Expected Client Input ===
        Authorization: Bearer <JWT_ACCESS_TOKEN>

    === Verification Performed ===
    JWTService.from_env().verify_token(...) checks signature, expiry, issuer, and
    audience according to the configured SHMC JWT settings.

    === Return Value ===
    Returns verified JWT claims as dict[str, Any]. Expected claims include sub,
    email, username, auth_code, auth_level, anonymous, projects, iat, exp, iss, aud.

    === Failure Behavior ===
    Raises HTTP 401. Authorization policy checks are intentionally handled elsewhere.

    =================================================================================== by Sziller & GPT-5 ==="""
    try:
        return JWTService.from_env().verify_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=jwt_error_message(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
