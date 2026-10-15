from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete, select

from app import cases, notifications
from app.database import SessionLocal
from app.models import Alert, AlertAssignment, CaseEvent, Notification, NotificationMaintenance, NotificationReceipt, User, utcnow
from test_cases import claim, make_case, operators


def rows(recipient, aid=None):
    with SessionLocal() as db:
        q = select(Notification).where(Notification.recipient == recipient)
        if aid is not None:
            q = q.where(Notification.alert_id == aid)
        return db.scalars(q.order_by(Notification.id)).all()


def test_case_hooks_roles_reassignment_closure_reopen_release(client, admin, operators, make_case):
    aid, _ = make_case()
    claim(client, aid, operators[0])
    assert [n.type for n in rows("admin", aid)] == ["case_claimed"]
    assert rows(operators[0][0], aid) == []
    assert client.post(f"/api/alerts/{aid}/assign", json={"owner": operators[1][0]}, headers=admin).status_code == 200
    assert [n.type for n in rows(operators[0][0], aid)] == ["case_reassigned"]
    assert [n.type for n in rows(operators[1][0], aid)] == ["case_assigned"]
    assert client.patch(f"/api/alerts/{aid}", json={"status": "closed", "outcome": "false_positive", "note": "Private verdict text should not enter notifications"}, headers=operators[1][1]).status_code == 200
    assert client.patch(f"/api/alerts/{aid}", json={"status": "open", "reason": "Private reopening explanation"}, headers=operators[1][1]).status_code == 200
    assert client.post(f"/api/alerts/{aid}/release", json={"reason": "Private release explanation"}, headers=operators[1][1]).status_code == 200
    admin_rows = rows("admin", aid)
    assert [n.type for n in admin_rows] == ["case_claimed", "case_closed", "case_reopened", "case_released"]
    assert "False positive" in admin_rows[1].message
    assert not any("Private" in n.message for n in admin_rows)
    # The same central event may be observed twice, but delivery is once.
    with SessionLocal() as db:
        event = db.scalar(select(CaseEvent).where(CaseEvent.alert_id == aid, CaseEvent.action == "claimed"))
        notifications.case_event(db, db.get(Alert, aid), event); db.commit()
    assert len(rows("admin", aid)) == 4


def test_escalation_hooks_and_private_data_not_copied(client, admin, operators, make_case):
    aid, uid = make_case(); claim(client, aid, operators[0])
    assert client.post("/api/admin/employees", json={"user_id": uid, "full_name": "NotificationPrivateName", "email": "notification-private@example.test", "phone": "+94 771234566", "supervisor_name": "NotificationPrivateSupervisor"}, headers=admin).status_code == 200
    filing = {"alert_id": aid, "summary": "PrivateNotificationSummaryMarker", "recommendation": "contact_user", "recommendation_note": "PrivateRecommendationMarker"}
    created = client.post("/api/escalations", json=filing, headers=operators[0][1]).json(); path = f"/api/escalations/{created['id']}"
    for suffix, body, headers in [
        ("acknowledge", None, admin), ("request-info", {"message": "PrivateRequestInfoMarker"}, admin),
        ("messages", {"message": "PrivateReplyMarker"}, operators[0][1]),
        ("contacted", {"contact_method": "phone", "summary": "PrivateContactMarker"}, admin),
        ("complete", {"handling_note": "PrivateHandlingNoteMarker"}, admin),
    ]:
        assert client.post(path + '/' + suffix, json=body, headers=headers).status_code == 200
    assert [n.type for n in rows(operators[0][0], aid)] == ["escalation_acknowledged", "escalation_needs_info", "escalation_contacted", "escalation_completed"]
    assert [n.type for n in rows("admin", aid)] == ["case_claimed", "escalation_submitted", "escalation_reply"]
    created = client.post("/api/escalations", json=filing, headers=operators[0][1]).json()
    assert client.post(f"/api/escalations/{created['id']}/withdraw", headers=operators[0][1]).status_code == 200
    assert rows("admin", aid)[-1].type == "escalation_withdrawn"
    for n in rows("admin", aid) + rows(operators[0][0], aid):
        assert "Private" not in n.title + n.message
        assert "notification-private@example.test" not in n.message
        assert "+94 771234566" not in n.message
    # Both roles' inbox serializers remain free of all private markers.
    for headers in (admin, operators[0][1]):
        result = client.get('/api/notifications?limit=100', headers=headers)
        assert 'PrivateContactMarker' not in result.text and 'NotificationPrivateName' not in result.text


def test_own_rows_mutations_filters_pagination_and_audits(client, admin, operators):
    with SessionLocal() as db:
        mine = notifications.notify(db, [operators[0][0]], "case_test", "Case test unique", "Case #9000", "/alerts/9000")[0]
        other = notifications.notify(db, [operators[1][0]], "escalation_test", "Other test", "Escalation #9000", "/escalations/9000")[0]
        db.commit(); mine_id, other_id = mine.id, other.id
    headers = operators[0][1]
    for suffix in ('read', 'unread'):
        assert client.post(f'/api/notifications/{other_id}/{suffix}', headers=headers).status_code == 404
    assert client.delete(f'/api/notifications/{other_id}', headers=headers).status_code == 404
    assert client.get('/api/notifications', params={'type': 'case_test', 'search': 'unique', 'limit': 1}, headers=headers).json()[0]['id'] == mine_id
    assert client.get('/api/notifications', params={'type': 'cases', 'before_id': mine_id}, headers=headers).status_code == 200
    assert all(n['id'] < mine_id for n in client.get('/api/notifications', params={'before_id': mine_id}, headers=headers).json())
    assert client.post(f'/api/notifications/{mine_id}/read', headers=headers).json()['read_at']
    assert mine_id not in [n['id'] for n in client.get('/api/notifications?unread=true', headers=headers).json()]
    assert client.post(f'/api/notifications/{mine_id}/unread', headers=headers).json()['read_at'] is None
    assert client.post('/api/notifications/read-all', headers=headers).status_code == 200
    assert client.get('/api/notifications/unread-count', headers=headers).json()['unread_count'] == 0
    assert client.delete(f'/api/notifications/{mine_id}', headers=headers).status_code == 200
    assert client.post(f'/api/notifications/{mine_id}/read', headers=headers).status_code == 404
    assert client.get('/api/notifications').status_code == 401
    with SessionLocal() as db:
        assert db.get(Notification, other_id).recipient == operators[1][0]


def test_reminder_once_even_after_dismiss_concurrently_and_retention(client, admin, make_case):
    aid, _ = make_case()
    with SessionLocal() as db:
        db.get(Alert, aid).created_at = utcnow() - timedelta(hours=25)
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.get('/api/notifications/unread-count', headers=admin), range(2)))
    assert all(r.status_code == 200 for r in results)
    reminders = [n for n in rows('admin', aid) if n.type == 'alert_unassigned_24h']
    assert len(reminders) == 1
    client.delete(f'/api/notifications/{reminders[0].id}', headers=admin)
    client.get('/api/notifications', headers=admin)
    assert not [n for n in rows('admin', aid) if n.type == 'alert_unassigned_24h']
    with SessionLocal() as db:
        old = notifications.notify(db, ['admin'], 'case_retention', 'Old', 'Case #1', '/alerts/1')[0]
        old.created_at = utcnow() - timedelta(days=31)
        db.execute(delete(NotificationMaintenance)); db.commit(); old_id = old.id
    client.get('/api/notifications/unread-count', headers=admin)
    with SessionLocal() as db:
        assert db.get(Notification, old_id) is None
        checkpoint = db.get(NotificationMaintenance, 'retention').last_run
        recent = notifications.notify(db, ['admin'], 'case_retention', 'Old 2', 'Case #2', '/alerts/2')[0]
        recent.created_at = utcnow() - timedelta(days=31); db.commit(); recent_id = recent.id
    client.get('/api/notifications/unread-count', headers=admin)
    with SessionLocal() as db:
        assert db.get(Notification, recent_id) is not None
        assert db.get(NotificationMaintenance, 'retention').last_run == checkpoint


def test_live_alert_cap_summary_silent_and_role_fanout(client, admin, operators, make_case):
    alerts = []
    for _ in range(11):
        aid, _ = make_case(category='Critical')
        alerts.append(aid)
    with SessionLocal() as db:
        batch = [db.get(Alert, aid) for aid in alerts]
        notifications.new_alerts(db, batch, silent=True)
        assert not db.scalars(select(Notification).where(Notification.alert_id.in_(alerts))).all()
        notifications.new_alerts(db, batch); db.commit()
        summary = db.scalars(select(Notification).where(Notification.recipient == 'admin', Notification.type == 'alert_batch')).all()
        assert summary[-1].title == '11 new High/Critical alerts'
        notifications.new_alerts(db, batch); db.commit()
        assert len(db.scalars(select(Notification).where(Notification.recipient == 'admin', Notification.type == 'alert_batch')).all()) == len(summary)
        notifications.new_alerts(db, batch[:10]); db.commit()
    assert sum(len([n for n in rows('admin', aid) if n.type == 'alert_new']) for aid in alerts) == 10
    assert not any(rows(operators[0][0], aid) for aid in alerts)


def test_reprocessing_silent_default_and_live_only_new_alerts(client, admin, make_case, monkeypatch):
    from app import api as api_module, pipeline
    aid, uid = make_case()
    with SessionLocal() as db:
        db.get(Alert, aid).narrative = 'Retained case context'
        db.commit()
    created_ids = []
    def process(db, user_id, cfg, honey):
        # Existing alert becomes Critical, but only the new incident is delivered.
        db.get(Alert, aid).category = 'Critical'
        now = utcnow() + timedelta(days=len(created_ids) + 1)
        pipeline._sync_alerts(db, uid, [{'start_time': now, 'last_time': now, 'peak_score': 95, 'breakdown': []}], cfg)
        created_ids.extend(a.id for a in db.info['notification_new_alerts'] if a.id not in created_ids)
    monkeypatch.setattr(pipeline, '_process_user', process)
    with SessionLocal() as db:
        pipeline.reprocess_users(db, [uid])
    assert not rows('admin', created_ids[-1])
    with SessionLocal() as db:
        pipeline.reprocess_users(db, [uid], silent=False)
    assert [n.type for n in rows('admin', created_ids[-1])] == ['alert_new']
    assert not [n for n in rows('admin', aid) if n.type == 'alert_new']
    with SessionLocal() as db:
        cases.record_event(db, db.get(Alert, created_ids[-1]), 'claimed', db.scalar(select(User).where(User.username == 'analyst')), silent=True)
        db.commit()
    assert not [n for n in rows('admin', created_ids[-1]) if n.type == 'case_claimed']
    seen = []
    monkeypatch.setattr(api_module, 'reprocess_users', lambda db, user_ids=None, **kwargs: seen.append(kwargs))
    with SessionLocal() as db:
        api_module._after_ingest({'accepted': 1, 'affected_users': [uid]}, db, BackgroundTasks())
    assert seen == [{'silent': False}]
    assert client.post('/api/admin/recompute', headers=admin).status_code == 200
    assert seen[-1] == {'silent': True}


def test_deleting_account_removes_notifications_and_delivery_keys(client, admin):
    name = 'notify_' + uuid4().hex[:10]
    created = client.post('/api/auth/accounts', json={'username': name, 'password': 'NotifyTesting#12345', 'role': 'analyst'}, headers=admin)
    assert created.status_code == 201
    with SessionLocal() as db:
        notifications.notify(db, [name], 'case_test', 'Case #1', 'Case #1', '/alerts/1', alert_id=1); db.commit()
        account_id = db.scalar(select(User.id).where(User.username == name))
    assert client.delete(f"/api/auth/accounts/{account_id}", headers=admin).status_code == 200
    with SessionLocal() as db:
        assert not db.scalar(select(Notification.id).where(Notification.recipient == name))
        assert not db.scalar(select(NotificationReceipt.id).where(NotificationReceipt.recipient == name))


def test_notification_delivery_rolls_back_with_the_callers_transaction(client, admin):
    key = uuid4().hex
    with SessionLocal() as db:
        notifications.notify(db, ['admin'], 'case_rollback', key, 'Case #1', '/alerts/1', dedupe_key=key)
        db.rollback()
    with SessionLocal() as db:
        assert not db.scalar(select(Notification.id).where(Notification.title == key))
        assert not db.scalar(select(NotificationReceipt.id).where(NotificationReceipt.delivery_key == key))
