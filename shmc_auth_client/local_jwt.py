"""Local-development JWT helpers for SHMC subprojects.

This module is intentionally for local testing only. It mints static HS256 JWTs
with the same claim shape that SHMC AuthRouter-issued tokens use, so subproject
endpoints can keep their normal authentication, project-access, and admin
authorization dependencies enabled while running outside the SHMC server.

=== by Sziller & GPT-5 ===
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

from jose import jwt

DEFAULT_LOCAL_SECRET = "shmc-local-dev-jwt-secret-not-for-production"
DEFAULT_ISSUER = "shmc-local-dev"
DEFAULT_AUDIENCE = "shmc-api"
DEFAULT_SUB = "local-dev-user"
DEFAULT_EMAIL = "local-dev@example.local"
DEFAULT_USERNAME = "local-dev"
DEFAULT_EXP_SECONDS = 30 * 24 * 60 * 60


def _normalize_projects(projects: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(projects, str):
        raw_projects = projects.split(",")
    else:
        raw_projects = list(projects)
    return [str(project).strip().upper() for project in raw_projects if str(project).strip()]


def build_local_dev_claims(
    *,
    project_code: str | None = None,
    projects: str | list[str] | tuple[str, ...] = (),
    auth_code: int = 2,
    sub: str = DEFAULT_SUB,
    email: str = DEFAULT_EMAIL,
    username: str = DEFAULT_USERNAME,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    expires_in_seconds: int | None = DEFAULT_EXP_SECONDS,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build SHMC-compatible local-development JWT claims."""
    now = int(time.time())
    project_list = _normalize_projects(projects)
    if project_code:
        normalized_project = str(project_code).strip().upper()
        if normalized_project and normalized_project not in project_list:
            project_list.append(normalized_project)

    claims: dict[str, Any] = {
        "sub": sub,
        "email": email,
        "username": username,
        "auth_code": int(auth_code),
        "auth_level": int(auth_code),
        "anonymous": False,
        "projects": project_list,
        "iat": now,
        "iss": issuer,
        "aud": audience,
    }
    if expires_in_seconds is not None:
        claims["exp"] = now + int(expires_in_seconds)
    if extra_claims:
        claims.update(extra_claims)
    return claims


def create_local_dev_token(
    *,
    secret: str = DEFAULT_LOCAL_SECRET,
    algorithm: str = "HS256",
    **claim_kwargs: Any,
) -> str:
    """Create an SHMC-compatible local-development JWT."""
    claims = build_local_dev_claims(**claim_kwargs)
    return jwt.encode(claims=claims, key=secret, algorithm=algorithm)


def local_dev_env(secret: str = DEFAULT_LOCAL_SECRET) -> dict[str, str]:
    """Return environment values needed for verifying local-development tokens."""
    return {
        "AUTH_JWT_ALGORITHM": "HS256",
        "AUTH_JWT_SECRET": secret,
        "AUTH_ISSUER": DEFAULT_ISSUER,
        "AUTH_AUDIENCE": DEFAULT_AUDIENCE,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create an SHMC local-development JWT.")
    parser.add_argument("--project", default=os.getenv("SHMC_LOCAL_JWT_PROJECT", "KARAK"))
    parser.add_argument("--projects", default=os.getenv("SHMC_LOCAL_JWT_PROJECTS", ""))
    parser.add_argument("--auth-code", type=int, default=int(os.getenv("SHMC_LOCAL_JWT_AUTH_CODE", "2")))
    parser.add_argument("--admin", action="store_true", help="Set auth_code to 32.")
    parser.add_argument("--sub", default=os.getenv("SHMC_LOCAL_JWT_SUB", DEFAULT_SUB))
    parser.add_argument("--email", default=os.getenv("SHMC_LOCAL_JWT_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--username", default=os.getenv("SHMC_LOCAL_JWT_USERNAME", DEFAULT_USERNAME))
    parser.add_argument(
        "--secret",
        default=os.getenv("SHMC_LOCAL_JWT_SECRET") or os.getenv("AUTH_JWT_SECRET") or DEFAULT_LOCAL_SECRET,
    )
    parser.add_argument("--issuer", default=os.getenv("SHMC_LOCAL_JWT_ISSUER", DEFAULT_ISSUER))
    parser.add_argument("--audience", default=os.getenv("SHMC_LOCAL_JWT_AUDIENCE", DEFAULT_AUDIENCE))
    parser.add_argument("--expires-in", type=int, default=DEFAULT_EXP_SECONDS)
    parser.add_argument("--claims", action="store_true", help="Print claims JSON as well as the token.")
    parser.add_argument("--env", action="store_true", help="Print local verification environment exports.")
    return parser


def main() -> None:
    args = _parser().parse_args()
    auth_code = 32 if args.admin else args.auth_code
    claims = build_local_dev_claims(
        project_code=args.project,
        projects=args.projects,
        auth_code=auth_code,
        sub=args.sub,
        email=args.email,
        username=args.username,
        issuer=args.issuer,
        audience=args.audience,
        expires_in_seconds=args.expires_in,
    )
    token = jwt.encode(claims=claims, key=args.secret, algorithm="HS256")

    if args.env:
        env_values = local_dev_env(secret=args.secret)
        env_values["AUTH_ISSUER"] = args.issuer
        env_values["AUTH_AUDIENCE"] = args.audience
        for key, value in env_values.items():
            print(f'export {key}="{value}"')
    if args.claims:
        print(json.dumps(claims, indent=2, sort_keys=True))
    print(token)


if __name__ == "__main__":
    main()
