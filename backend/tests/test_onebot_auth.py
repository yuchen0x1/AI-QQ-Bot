"""OneBot 接入端点鉴权测试：未配置凭据时必须拒绝（fail-closed）。"""

from __future__ import annotations

from app.api.onebot import _check_token
from app.core.security import encrypt_secret
from app.models import Account


def _account(access_token_enc: str | None) -> Account:
    return Account(name="t", protocol="onebot11", account_id="10001", access_token_enc=access_token_enc)


def test_rejects_when_token_not_configured():
    account = _account(None)
    assert _check_token(account, None) is False
    assert _check_token(account, "anything") is False


def test_rejects_when_token_undecryptable():
    # 密文损坏或 SECRET_KEY 轮换后无法解密，必须拒绝而不是放行
    account = _account("not-a-valid-fernet-token")
    assert _check_token(account, None) is False
    assert _check_token(account, "anything") is False


def test_accepts_only_matching_token():
    account = _account(encrypt_secret("s3cret-token"))
    assert _check_token(account, None) is False
    assert _check_token(account, "wrong") is False
    assert _check_token(account, "s3cret-token") is True
