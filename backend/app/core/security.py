"""密码哈希、JWT、敏感字段加解密。"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


# --------------------------------------------------------------------------
# 密码
# --------------------------------------------------------------------------
# bcrypt 的输入上限是 72 字节（bcrypt 5.x 超长直接抛 ValueError，4.x 静默截断）。
# 中文密码 24 个字符就会超限，因此先做一次 SHA-256 预哈希再交给 bcrypt：
# 输出是固定长度、字母数字组成的字符串，既避开 72 字节限制，也没有 null 字节问题。
# 预哈希带版本前缀，将来更换算法时可以平滑迁移。
_BCRYPT_PREFIX = "sha256:"


def _bcrypt_input(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return _BCRYPT_PREFIX + bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        if hashed.startswith(_BCRYPT_PREFIX):
            return bcrypt.checkpw(_bcrypt_input(password), hashed[len(_BCRYPT_PREFIX):].encode("utf-8"))
        # 兼容升级前的历史哈希：bcrypt 4.x 对超过 72 字节的输入静默截断，5.x 则直接抛
        # ValueError。这里显式截断，保证老用户（尤其是中文长密码）不会因升级被锁在门外。
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """判断哈希是否为旧格式（未经过 SHA-256 预哈希），用于登录成功后原地升级。"""
    return not (hashed or "").startswith(_BCRYPT_PREFIX)


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def password_stamp(password_hash: str) -> str:
    """由密码哈希派生的版本标记：密码变更后旧 JWT 立即失效，且不可逆推出密码。"""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_access_token(
    subject: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
    *,
    password_hash: str | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
    }
    if password_hash:
        payload["pwd_v"] = password_stamp(password_hash)
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def token_matches_user(payload: dict[str, Any], password_hash: str) -> bool:
    """校验 JWT 中的密码版本标记；缺失或 mismatch 一律视为失效。"""
    return payload.get("pwd_v") == password_stamp(password_hash)


# --------------------------------------------------------------------------
# 敏感配置加密（QQ 凭据 / AI Key / GitHub Token）
# --------------------------------------------------------------------------
def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_secret(value: str | None, keep: int = 4) -> str:
    """用于前端展示：只回显尾部若干位。"""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * max(4, len(value) - keep) + value[-keep:]
