"""Short WebSocket tickets must authenticate against their originating login session."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.api.ws import _authenticate, _session_ref
from app.core.security import decode_access_token
from app.models import AuthSession


async def test_ticket_uses_origin_session_and_is_rejected_after_revocation(client, db):
    login = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
    access = login.json()['access_token']
    headers = {'Authorization': f'Bearer {access}'}
    response = await client.post('/api/ws/ticket', headers=headers)
    ticket = response.json()['ticket']
    ticket_data = decode_access_token(ticket)
    access_data = decode_access_token(access)
    assert ticket_data['jti'] != access_data['jti']
    assert _session_ref(ticket)[0] == access_data['jti']
    assert (await _authenticate(ticket)).username == 'admin'
    # The short ticket cannot serve as an ordinary API credential.
    denied = await client.get('/api/auth/me', headers={'Authorization': f'Bearer {ticket}'})
    assert denied.status_code == 401
    session = await db.scalar(select(AuthSession).where(AuthSession.jti == access_data['jti']))
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    assert await _authenticate(ticket) is None
