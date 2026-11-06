"""QQ 官方机器人 Webhook 回调的 Ed25519 签名工具。

官方文档：
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html
- https://bot.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html

平台用同一个 AppSecret（Bot Secret）派生 Ed25519 密钥对：把 Secret 的 UTF-8
字节不断自拼接（repeat）到至少 32 字节，取前 32 字节作为 seed。

- 回调地址验证（op=13，无签名头）：服务端用私钥签 ``event_ts + plain_token``，
  返回 hex 签名，用于向平台证明持有 Secret。
- 事件推送（op=0）：平台用私钥签 ``X-Signature-Timestamp + 原始 HTTP body``，
  服务端用公钥验签，防止伪造与篡改。
"""
from __future__ import annotations

import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SEED_SIZE = 32
SIGNATURE_SIZE = 64


def derive_seed(secret: str) -> bytes:
    """按官方 Go 示例的 repeat 规则把 AppSecret 扩展成 32 字节 Ed25519 seed。"""
    raw = (secret or "").encode("utf-8")
    if not raw:
        raise ValueError("AppSecret 为空，无法生成 Webhook 签名密钥")
    while len(raw) < SEED_SIZE:
        raw = raw + raw
    return raw[:SEED_SIZE]


def derive_private_key(secret: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(derive_seed(secret))


def public_key_bytes(secret: str) -> bytes:
    """返回 32 字节裸公钥，主要用于与官方 DEMO 对照验证派生是否正确。"""
    return derive_private_key(secret).public_key().public_bytes_raw()


def sign_callback_validation(secret: str, event_ts: str, plain_token: str) -> str:
    """生成 op=13 回调验证响应中的 signature（小写 hex，128 字符）。"""
    message = f"{event_ts}{plain_token}".encode("utf-8")
    return derive_private_key(secret).sign(message).hex()


def verify_event_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    signature_hex: str,
    *,
    max_age_seconds: int = 300,
) -> tuple[bool, str]:
    """校验 op=0 事件推送签名，返回 (是否通过, 失败原因)。

    ``timestamp`` 必须使用请求头的原始字符串参与拼接，不能做数值转换后重组，
    否则会破坏签名体。``body`` 必须是未解析、未重新序列化的原始字节。
    """
    if not secret:
        return False, "账号未配置 AppSecret"
    if not timestamp or not signature_hex:
        return False, "缺少 X-Signature-Timestamp 或 X-Signature-Ed25519 请求头"
    try:
        stamp = int(timestamp)
    except (TypeError, ValueError):
        return False, "X-Signature-Timestamp 不是合法时间戳"
    if max_age_seconds > 0 and abs(time.time() - stamp) > max_age_seconds:
        return False, "X-Signature-Timestamp 超出允许的时间窗口"
    try:
        signature = bytes.fromhex(signature_hex)
    except (TypeError, ValueError):
        return False, "X-Signature-Ed25519 不是合法 hex"
    if len(signature) != SIGNATURE_SIZE or signature[SIGNATURE_SIZE - 1] & 224:
        return False, "X-Signature-Ed25519 长度或格式不合法"
    signed_bytes = timestamp.encode("utf-8") + body
    try:
        derive_private_key(secret).public_key().verify(signature, signed_bytes)
    except (InvalidSignature, ValueError):
        return False, "Ed25519 签名不匹配"
    return True, ""
