"""=== Module: shmc_auth_client.jwt_service =====================================================
Reusable SHMC JWT verification support for service/router projects.

=== Purpose ===
This module is intentionally client-side: it verifies SHMC JWT access tokens using
the public verification configuration. It does not know about Auth DB tables,
passwords, registration, or API-key issuance.

=== Deployment Model ===
AuthRouter signs tokens. Subprojects such as Karak, Optimizer, Aquaponics, and
Room routers import this module to verify signed tokens and read trusted claims.

=================================================================================== by Sziller & GPT-5 ==="""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jose import JWTError, jwt


@dataclass(frozen=True)
class JWTService:
    """=== Class: JWTService ========================================================================
    Reusable JWT verifier for SHMC access tokens.

    === Purpose ===
    This lightweight service reads JWT verification settings and validates tokens.
    In RS256 production mode it needs only the public key, so subprojects can verify
    tokens without being able to mint them.

    === Configuration ===
    RS256:
      - AUTH_JWT_ALGORITHM="RS256"
      - AUTH_JWT_PUBLIC_KEY_PATH="/path/to/jwt_public.pem"
      - AUTH_ISSUER="https://api.sziller.eu/app/auth"
      - AUTH_AUDIENCE="shmc-api"

    HS256 compatibility mode:
      - AUTH_JWT_ALGORITHM="HS256"
      - AUTH_JWT_SECRET or AUTH_SECRET_KEY

    === Security Boundary ===
    This client package should not receive AUTH_JWT_PRIVATE_KEY_PATH in subprojects.
    The private key belongs only to AuthRouter.

    =================================================================================== by Sziller & GPT-5 ==="""

    algorithm: str
    issuer: str
    audience: str
    public_key_path: str | None = None
    shared_secret: str | None = None

    @classmethod
    def from_env(cls) -> "JWTService":
        """=== Method: JWTService.from_env ===========================================================
        Build a verifier from environment variables.

        === Failure Behavior ===
        Raises RuntimeError for unsupported algorithms or missing HS256 secrets. RS256
        public-key file errors are raised when verify_token(...) is called.

        =================================================================================== by Sziller & GPT-5 ==="""
        algorithm = (os.getenv("AUTH_JWT_ALGORITHM") or os.getenv("AUTH_ALGO") or "RS256").upper()
        if algorithm not in {"RS256", "HS256"}:
            raise RuntimeError(
                f"Unsupported AUTH_JWT_ALGORITHM {algorithm!r}. SHMC JWT verification supports RS256 and HS256."
            )

        shared_secret = None
        if algorithm == "HS256":
            shared_secret = os.getenv("AUTH_JWT_SECRET") or os.getenv("AUTH_SECRET_KEY")
            if not shared_secret:
                raise RuntimeError("AUTH_JWT_SECRET is required when AUTH_JWT_ALGORITHM='HS256'.")

        return cls(
            algorithm=algorithm,
            issuer=os.getenv("AUTH_ISSUER") or "https://api.sziller.eu/app/auth",
            audience=os.getenv("AUTH_AUDIENCE") or "shmc-api",
            public_key_path=os.getenv("AUTH_JWT_PUBLIC_KEY_PATH"),
            shared_secret=shared_secret,
        )

    @staticmethod
    def _read_required_key_file(env_name: str, path_value: str | None) -> str:
        """=== Method: JWTService._read_required_key_file ============================================
        Read a required PEM key file with configuration-oriented error messages.

        =================================================================================== by Sziller & GPT-5 ==="""
        if not path_value or not path_value.strip():
            raise RuntimeError(f"{env_name} is required when AUTH_JWT_ALGORITHM='RS256'.")

        key_path = Path(path_value).expanduser()
        try:
            return key_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Could not read {env_name} at {str(key_path)!r}: {exc}") from exc

    def _verification_key(self) -> str:
        """=== Method: JWTService._verification_key ===================================================
        Return key material used for JWT verification.

        =================================================================================== by Sziller & GPT-5 ==="""
        if self.algorithm == "RS256":
            return self._read_required_key_file("AUTH_JWT_PUBLIC_KEY_PATH", self.public_key_path)
        if self.algorithm == "HS256" and self.shared_secret:
            return self.shared_secret
        raise RuntimeError(f"Unsupported AUTH_JWT_ALGORITHM {self.algorithm!r}.")

    def verify_token(self, token: str) -> dict[str, Any]:
        """=== Method: JWTService.verify_token =======================================================
        Verify an SHMC JWT and return decoded claims.

        === Verification Performed ===
        python-jose validates signature, algorithm, exp, aud, and iss.

        =================================================================================== by Sziller & GPT-5 ==="""
        return jwt.decode(
            token=token,
            key=self._verification_key(),
            algorithms=[self.algorithm],
            audience=self.audience,
            issuer=self.issuer,
        )


def jwt_error_message(exc: Exception) -> str:
    """=== Function: jwt_error_message ===============================================================
    Convert JWT-related exceptions into compact HTTP 401 detail text.

    =================================================================================== by Sziller & GPT-5 ==="""
    if isinstance(exc, JWTError):
        return str(exc) or exc.__class__.__name__
    return str(exc) or exc.__class__.__name__
