"""Reusable FastAPI authorization policies for SHMC JWT claims.

This module sits above ``shmc_auth_client.security``:
  - security authenticates a request and returns verified JWT claims
  - policies authorize those verified claims for common SHMC rules

Endpoint code and router code should use these dependency factories instead of
manually parsing JWTs or duplicating auth_code/project checks.

=== by Sziller & GPT-5 ===
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status

from shmc_auth_client.auth_code import AUTH_BIT_ADMIN, AUTH_BIT_REGISTERED, has_auth_bit
from shmc_auth_client.security import get_current_claims


Claims = dict[str, Any]
PolicyDependency = Callable[..., Any]


def get_auth_code_from_claims(claims: Claims) -> int:
    """=== Function: get_auth_code_from_claims ================================================
    Return the canonical auth_code integer from verified claims.

    === Rule ===
    auth_code is canonical. auth_level is accepted only as a compatibility fallback.

    =================================================================================== by Sziller & GPT-5 ==="""
    raw_auth_code = claims.get("auth_code")
    if raw_auth_code is None:
        raw_auth_code = claims.get("auth_level")
    try:
        return int(raw_auth_code or 0)
    except (TypeError, ValueError):
        return 0


def get_projects_from_claims(claims: Claims) -> set[str]:
    """=== Function: get_projects_from_claims ================================================
    Return normalized project codes from verified claims.

    =================================================================================== by Sziller & GPT-5 ==="""
    raw_projects = claims.get("projects") or []
    if isinstance(raw_projects, str):
        raw_projects = [raw_projects]
    try:
        return {str(project).strip().upper() for project in raw_projects if str(project).strip()}
    except TypeError:
        return set()


def _normalized_project_code(project_code: str) -> str:
    normalized = str(project_code or "").strip().upper()
    if not normalized:
        raise ValueError("project_code must be non-empty.")
    return normalized


def _validate_bit_index(bit_index: int) -> int:
    index = int(bit_index)
    if index < 0:
        raise ValueError("bit_index must be >= 0.")
    return index


def _authorization_failed(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_auth_bit(bit_index: int) -> PolicyDependency:
    """=== Function: require_auth_bit ==========================================================
    Build a dependency that requires one auth_code bit and returns verified claims.

    =================================================================================== by Sziller & GPT-5 ==="""
    required_bit = _validate_bit_index(bit_index)

    async def dependency(claims: Claims = Depends(get_current_claims)) -> Claims:
        auth_code = get_auth_code_from_claims(claims)
        if not has_auth_bit(auth_code, required_bit):
            _authorization_failed(f"auth_code bit {required_bit} required.")
        return claims

    return dependency


def require_any_auth_bit(*bit_indexes: int) -> PolicyDependency:
    """=== Function: require_any_auth_bit ======================================================
    Build a dependency that requires at least one auth_code bit from a set.

    =================================================================================== by Sziller & GPT-5 ==="""
    required_bits = tuple(_validate_bit_index(bit_index) for bit_index in bit_indexes)
    if not required_bits:
        raise ValueError("At least one bit index is required.")

    async def dependency(claims: Claims = Depends(get_current_claims)) -> Claims:
        auth_code = get_auth_code_from_claims(claims)
        if not any(has_auth_bit(auth_code, bit_index) for bit_index in required_bits):
            _authorization_failed(f"One of auth_code bits {required_bits} is required.")
        return claims

    return dependency


def require_project_access(project_code: str) -> PolicyDependency:
    """=== Function: require_project_access ====================================================
    Build a dependency that requires project access in verified JWT claims.

    =================================================================================== by Sziller & GPT-5 ==="""
    required_project = _normalized_project_code(project_code)

    async def dependency(claims: Claims = Depends(get_current_claims)) -> Claims:
        projects = get_projects_from_claims(claims)
        if required_project not in projects:
            _authorization_failed(f"{required_project} project access required.")
        return claims

    return dependency


def require_registered_project_access(project_code: str) -> PolicyDependency:
    """=== Function: require_registered_project_access ========================================
    Build a dependency requiring registered-user bit and project access.

    =================================================================================== by Sziller & GPT-5 ==="""
    required_project = _normalized_project_code(project_code)

    async def dependency(claims: Claims = Depends(get_current_claims)) -> Claims:
        auth_code = get_auth_code_from_claims(claims)
        projects = get_projects_from_claims(claims)
        if not has_auth_bit(auth_code, AUTH_BIT_REGISTERED):
            _authorization_failed(f"auth_code bit {AUTH_BIT_REGISTERED} required.")
        if required_project not in projects:
            _authorization_failed(f"{required_project} project access required.")
        return claims

    return dependency


def require_admin_claims() -> PolicyDependency:
    """=== Function: require_admin_claims ======================================================
    Build a dependency that requires the global admin auth_code bit.

    =================================================================================== by Sziller & GPT-5 ==="""
    return require_auth_bit(AUTH_BIT_ADMIN)


def require_project_admin_claims(project_code: str) -> PolicyDependency:
    """=== Function: require_project_admin_claims =============================================
    Build a dependency requiring admin bit and project access.

    =================================================================================== by Sziller & GPT-5 ==="""
    required_project = _normalized_project_code(project_code)

    async def dependency(claims: Claims = Depends(get_current_claims)) -> Claims:
        auth_code = get_auth_code_from_claims(claims)
        projects = get_projects_from_claims(claims)
        if not has_auth_bit(auth_code, AUTH_BIT_ADMIN):
            _authorization_failed(f"auth_code bit {AUTH_BIT_ADMIN} required.")
        if required_project not in projects:
            _authorization_failed(f"{required_project} project access required.")
        return claims

    return dependency
