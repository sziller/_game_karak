"""=== Package: shmc_auth_client ==============================================================
Compact reusable SHMC authentication client package.

=== Purpose ===
Copy or package this directory into SHMC subprojects that need to protect FastAPI
endpoints with central SHMC JWT authentication and authorization policies.

=== Contains ===
  - auth_code: canonical auth_code bit constants and helpers
  - jwt_service: public-key JWT verification service
  - security: FastAPI JWT bearer dependency
  - policies: reusable authorization dependency factories
  - local_jwt: local-development JWT generator for subproject tests

=== Does Not Contain ===
  - AuthRouter
  - Auth DB/session code
  - registration/login/password code
  - API-key issuance or DB-backed API-key verification

=================================================================================== by Sziller & GPT-5 ==="""

from shmc_auth_client.auth_code import (
    AUTH_BIT_ADMIN,
    AUTH_BIT_FUNDED,
    AUTH_BIT_OWNER,
    AUTH_BIT_POWER_USER,
    AUTH_BIT_REGISTERED,
    AUTH_BIT_RESERVED,
    AUTH_BIT_SIGNER,
    AUTH_CODE_ADMIN,
    AUTH_CODE_FUNDED,
    AUTH_CODE_OWNER,
    AUTH_CODE_POWER_USER,
    AUTH_CODE_REGISTERED,
    AUTH_CODE_SIGNER,
    has_auth_bit,
    is_auth_admin,
    is_nth_bit_set,
)
from shmc_auth_client.jwt_service import JWTService, jwt_error_message
from shmc_auth_client.policies import (
    get_auth_code_from_claims,
    get_projects_from_claims,
    require_admin_claims,
    require_any_auth_bit,
    require_auth_bit,
    require_project_access,
    require_project_admin_claims,
    require_registered_project_access,
)
from shmc_auth_client.security import (
    extract_bearer_token,
    get_current_claims,
    oauth2_scheme,
    require_auth_admin_claims,
    verify_token_from_authorization_header,
)

__all__ = [
    "AUTH_BIT_ADMIN",
    "AUTH_BIT_FUNDED",
    "AUTH_BIT_OWNER",
    "AUTH_BIT_POWER_USER",
    "AUTH_BIT_REGISTERED",
    "AUTH_BIT_RESERVED",
    "AUTH_BIT_SIGNER",
    "AUTH_CODE_ADMIN",
    "AUTH_CODE_FUNDED",
    "AUTH_CODE_OWNER",
    "AUTH_CODE_POWER_USER",
    "AUTH_CODE_REGISTERED",
    "AUTH_CODE_SIGNER",
    "JWTService",
    "extract_bearer_token",
    "get_auth_code_from_claims",
    "get_current_claims",
    "get_projects_from_claims",
    "has_auth_bit",
    "is_auth_admin",
    "is_nth_bit_set",
    "jwt_error_message",
    "oauth2_scheme",
    "require_admin_claims",
    "require_any_auth_bit",
    "require_auth_admin_claims",
    "require_auth_bit",
    "require_project_access",
    "require_project_admin_claims",
    "require_registered_project_access",
    "verify_token_from_authorization_header",
]
