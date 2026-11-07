"""标准 TOTP 生成与校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from urllib.parse import quote


_PERIOD = 30
_DIGITS = 6
_WINDOW = 1


def normalize_secret(secret: str) -> str:
    return "".join(secret.strip().upper().split()).rstrip("=")


def generate_secret() -> str:
    import secrets

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _counter(secret: str, counter: int) -> int:
    normalized = normalize_secret(secret)
    padded = normalized + "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return binary % (10**_DIGITS)


def generate_code(secret: str, now: int | None = None) -> str:
    current = int((now if now is not None else time.time()) // _PERIOD)
    return f"{_counter(secret, current):0{_DIGITS}d}"


def matching_counter(secret: str, code: str, now: int | None = None) -> int | None:
    if not secret or not code.isdigit() or len(code) != _DIGITS:
        return None
    current = int((now if now is not None else time.time()) // _PERIOD)
    expected = int(code)
    for counter in range(current - _WINDOW, current + _WINDOW + 1):
        if counter >= 0 and hmac.compare_digest(f"{_counter(secret, counter):0{_DIGITS}d}", f"{expected:0{_DIGITS}d}"):
            return counter
    return None


def provisioning_uri(secret: str, account_name: str, issuer: str) -> str:
    label = f"{issuer}:{account_name}"
    return (
        "otpauth://totp/"
        f"{quote(label, safe='')}?secret={quote(normalize_secret(secret))}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD}"
    )
