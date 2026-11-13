"""The product exposes only official QQ bot authentication and transports."""
import pytest
from app.adapters.base import AdapterError
from app.models import Account
from app.services.account_manager import build_adapter


@pytest.mark.parametrize("protocol", ["onebot11", "mock", "unknown"])
async def test_api_rejects_removed_protocols(client, admin_headers, protocol):
    response = await client.post('/api/accounts', headers=admin_headers,
                                 json={"name":"unsupported", "protocol":protocol})
    assert response.status_code == 422


@pytest.mark.parametrize("path", ['/api/napcat/instances', '/api/onebot/v11/123/event'])
async def test_removed_routes_are_not_registered(client, admin_headers, path):
    method = client.post if '/event' in path else client.get
    response = await method(path, headers=admin_headers)
    assert response.status_code == 404


def test_runtime_rejects_retired_account_even_if_old_database_contains_one():
    for protocol in ('onebot11', 'mock'):
        with pytest.raises(AdapterError, match="仅支持 QQ 官方机器人"):
            build_adapter(Account(id=999, account_id='retired', name='old', protocol=protocol))
