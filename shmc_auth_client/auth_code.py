"""=== Module: shmc_auth_client.auth_code ================================================================
Canonical helpers and constants for SHMC AuthUser.auth_code bitfield handling.

=== Purpose ===
SHMC auth_code is an integer made up of binary authorization switches. This module
keeps those bit positions, composed template values, and helper functions in one
place so routers do not reinvent bit checks.

=================================================================================== by Sziller & GPT-5 ==="""

from __future__ import annotations

from typing import Optional

AUTH_BIT_RESERVED = 0
AUTH_BIT_REGISTERED = 1
AUTH_BIT_SIGNER = 2
AUTH_BIT_FUNDED = 3
AUTH_BIT_POWER_USER = 4
AUTH_BIT_ADMIN = 5
AUTH_BIT_OWNER = 6

AUTH_CODE_REGISTERED = 1 << AUTH_BIT_REGISTERED
AUTH_CODE_SIGNER = AUTH_CODE_REGISTERED | (1 << AUTH_BIT_SIGNER)
AUTH_CODE_FUNDED = AUTH_CODE_SIGNER | (1 << AUTH_BIT_FUNDED)
AUTH_CODE_POWER_USER = AUTH_CODE_FUNDED | (1 << AUTH_BIT_POWER_USER)
AUTH_CODE_ADMIN = 1 << AUTH_BIT_ADMIN
AUTH_CODE_OWNER = 1 << AUTH_BIT_OWNER


def is_nth_bit_set(number: int, n: int) -> bool:
    """=== Function: is_nth_bit_set ================================================================
    Determine whether the n-th binary bit of an integer is set.

    === Purpose ===
    This is the minimal generic bit-check primitive:

        (number & (1 << n)) != 0

    It is intentionally not SHMC-specific. has_auth_bit(...) wraps this helper for
    AuthUser.auth_code values and handles Optional[int] input.

    === Parameters ===
    number:
      Integer value to inspect.

    n:
      Zero-based bit position to check. Bit 0 is the least significant bit.

    === Return Value ===
    True if bit n is set to 1, otherwise False.

    === Failure Behavior ===
    Raises ValueError when n is negative.

    =================================================================================== by Sziller & GPT-5 ==="""
    if n < 0:
        raise ValueError("n must be >= 0")
    return (number & (1 << n)) != 0


def has_auth_bit(auth_code: Optional[int], bit_index: int) -> bool:
    """=== Helper function: has_auth_bit =============================================================
    Determines whether a given authorization code has a specific binary bit set.

    === Example ===
        auth_code = 6   -> binary: 0b0110
        bit positions:   3   2   1   0
                         0   1   1   0
        Function (6, 2) -> True   # bit at position 2 is 1
        Function (6, 0) -> False  # bit at position 0 is 0

    === Parameters ===
    auth_code:
      Decimal representation of the authorization code. None is treated as 0.

    bit_index:
      Zero-based bit position to check. 0 means least significant bit.

    === Returns ===
    bool:
      True if the bit at bit_index is set to 1, otherwise False.

    === Failure Behavior ===
    Raises ValueError when bit_index is negative.

    ============================================================================ by Sziller & GPT-5 ==="""
    if bit_index < 0:
        raise ValueError("bit_index must be >= 0")
    code = int(auth_code or 0)
    return is_nth_bit_set(number=code, n=bit_index)


def is_auth_admin(auth_code: Optional[int]) -> bool:
    """=== Function: is_auth_admin ==================================================================
    Return whether auth_code contains the Auth Admin switch.

    === Rule ===
    Auth Admin means bit 5 is set:

        1 << 5 == 32

    A numerically high auth_code is not enough. For example, auth_code=15 is not an
    admin code because bit 5 is not set.

    =================================================================================== by Sziller & GPT-5 ==="""
    return has_auth_bit(auth_code=auth_code, bit_index=AUTH_BIT_ADMIN)
