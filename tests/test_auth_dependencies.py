from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from shmc_auth_client.jwt_service import JWTService
from shmc_auth_client.local_jwt import create_local_dev_token
from shmc_auth_client.policies import require_project_admin_claims, require_registered_project_access
from shmc_auth_client.security import extract_bearer_token


LOCAL_SECRET = "shmc-local-dev-jwt-secret-not-for-production"


def local_token(*, project: str = "KARAK", auth_code: int = 2) -> str:
    return create_local_dev_token(
        secret=LOCAL_SECRET,
        project_code=project,
        auth_code=auth_code,
    )


def verify_claims(token: str) -> dict:
    return JWTService(
        algorithm="HS256",
        shared_secret=LOCAL_SECRET,
        issuer="shmc-local-dev",
        audience="shmc-api",
    ).verify_token(token)


def run_dependency(dependency, claims: dict) -> dict:
    return asyncio.run(dependency(claims))


def test_missing_bearer_header_is_unauthorized():
    with pytest.raises(HTTPException) as exc:
        extract_bearer_token(None)

    assert exc.value.status_code == 401


def test_registered_karak_claims_pass_project_policy():
    claims = verify_claims(local_token())
    dependency = require_registered_project_access("KARAK")

    assert run_dependency(dependency, claims) == claims


def test_wrong_project_is_forbidden():
    claims = verify_claims(local_token(project="OPTIMIZER"))
    dependency = require_registered_project_access("KARAK")

    with pytest.raises(HTTPException) as exc:
        run_dependency(dependency, claims)

    assert exc.value.status_code == 403


def test_project_admin_policy_requires_admin_bit_and_project():
    user_claims = verify_claims(local_token(auth_code=2))
    admin_claims = verify_claims(local_token(auth_code=32))
    dependency = require_project_admin_claims("KARAK")

    with pytest.raises(HTTPException) as exc:
        run_dependency(dependency, user_claims)

    assert exc.value.status_code == 403
    assert run_dependency(dependency, admin_claims) == admin_claims
