from datetime import datetime
from app.database import SessionLocal
from app.models import AuditLog


def test_audit_filters_date_actor_and_access(client, admin, analyst):
    with SessionLocal() as db:
        rows = [AuditLog(timestamp=datetime(2025, 1, 1, hour), actor=actor, role='admin', action='filter_test')
                for hour, actor in [(9, 'audit-filter-a'), (10, 'audit-filter-a'), (11, 'audit-filter-b')]]
        db.add_all(rows)
        db.commit()
        expected = rows[1].id
    params = {'actor': 'audit-filter-a', 'start': '2025-01-01T15:30:00+05:30', 'end': '2025-01-01T10:00:00Z', 'limit': 1}
    response = client.get('/api/audit', params=params, headers=admin)
    assert response.status_code == 200
    assert [row['id'] for row in response.json()] == [expected]
    assert len(client.get('/api/audit', params={'actor': 'audit-filter-a', 'end': '2025-01-01T09:00:00'}, headers=admin).json()) == 1
    assert client.get('/api/audit', params={'start': '2025-01-02', 'end': '2025-01-01'}, headers=admin).status_code == 422
    assert client.get('/api/audit', params={'start': 'invalid'}, headers=admin).status_code == 422
    assert client.get('/api/audit', params=params, headers=analyst).status_code == 403
