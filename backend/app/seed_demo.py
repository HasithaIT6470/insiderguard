"""Separate, verified demo seed. --reset explicitly replaces the selected database."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from contextlib import ExitStack, contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import DateTime, func, select

from . import ai, api, cases, employees, escalations, evaluation, notifications, pipeline, resolutions
from .database import Base, SessionLocal, engine, get_db, init_db
from .demo_dataset import PERSONAS, SUPERVISORS, default_end, generate_demo
from .models import (
    Alert, AlertAssignment, AlertResolution, AuditLog, Baseline, CaseEvent, CaseNote, DemoSeedRun,
    EmployeeContact, EmployeeProfile, Escalation, EscalationEvent, EscalationMessage, EvaluationRun,
    Event, Honeytoken, Notification, NotificationReceipt, ParseError, Subject, User, utcnow,
)
from . import config
from .security import audit, get_current_user, hash_password

EXTRA_PASSWORDS = {'analyst2': 'DemoReview#23456', 'analyst3': 'DemoReview#34567'}
DEFAULT_GUIDE = Path(__file__).resolve().parents[2] / 'docs' / 'DEMO_GUIDE.md'
WORKFLOW_MODELS = (User, EmployeeProfile, AlertAssignment, CaseEvent, CaseNote, AlertResolution,
                   Escalation, EscalationEvent, EscalationMessage, EmployeeContact, Notification, AuditLog, EvaluationRun)


@contextmanager
def clock(when):
    """Seed-only clock; application code and its authorization/validation stay intact."""
    with ExitStack() as stack:
        for module in (api, cases, employees, escalations, evaluation, notifications, pipeline, resolutions):
            stack.enter_context(patch.object(module, 'utcnow', return_value=when))
        yield


def call_at(session, when, function, *args, **kwargs):
    before = {model: session.scalar(select(func.max(model.id))) or 0 for model in WORKFLOW_MODELS}
    with clock(when):
        result = function(*args, **kwargs)
    session.flush()
    # SQLAlchemy column defaults retain their original callable. Back-date only
    # rows created by this action, rather than rewriting other historical rows.
    for model in WORKFLOW_MODELS:
        for row in session.scalars(select(model).where(model.id > before[model])):
            for column in model.__table__.columns:
                if isinstance(column.type, DateTime):
                    value = getattr(row, column.name)
                    if value and value > when:
                        setattr(row, column.name, when)
    session.commit()
    return result


def workflow_snapshot(db):
    def rows(model, fields):
        return [{key: (value.isoformat() if isinstance(value, (datetime, date)) else value)
                 for key in fields for value in [getattr(row, key)]}
                for row in db.scalars(select(model).order_by(model.id))]
    return {
        'alerts': rows(Alert, ('id', 'user_id', 'start_time', 'last_time', 'peak_score', 'status')),
        'assignments': rows(AlertAssignment, ('id', 'alert_id', 'owner', 'assigned_at', 'updated_at')),
        'resolutions': rows(AlertResolution, ('id', 'alert_id', 'outcome', 'note', 'resolved_at', 'reopened_at', 'reopened_by', 'reopen_reason')),
        'case_events': rows(CaseEvent, ('id', 'alert_id', 'action', 'actor', 'created_at', 'detail')),
        'escalations': rows(Escalation, ('id', 'alert_id', 'created_by', 'status', 'snapshot', 'created_at', 'completed_at')),
        'escalation_events': rows(EscalationEvent, ('id', 'escalation_id', 'action', 'actor', 'from_status', 'to_status', 'created_at')),
        'contacts': rows(EmployeeContact, ('id', 'user_id', 'escalation_id', 'contacted_by', 'method', 'summary', 'created_at')),
    }


def seed_accounts(db, when):
    admin_name, analyst_name = config.DEFAULT_ADMIN_USER, config.DEFAULT_ANALYST_USER
    names = [admin_name, analyst_name, 'analyst2', 'analyst3']
    if len(set(names)) != 4:
        raise ValueError('Configured admin/analyst usernames must differ from analyst2 and analyst3')
    admin = User(username=admin_name, role='admin', password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD, admin_name), created_at=when)
    db.add(admin); audit(db, admin, 'create_demo_admin', admin_name); db.commit()
    credentials = {admin_name: config.DEFAULT_ADMIN_PASSWORD, analyst_name: config.DEFAULT_ANALYST_PASSWORD, **EXTRA_PASSWORDS}
    for name in names[1:]:
        call_at(db, when, api.create_account, api.AccountIn(username=name, password=credentials[name], role='analyst'), db=db, admin=admin)
    for row in db.scalars(select(AuditLog)):
        row.timestamp = when
    db.commit()
    return admin, [db.scalar(select(User).where(User.username == name)) for name in names[1:]], credentials


def seed_profiles(db, admin, start, hire):
    for index, (uid, full_name, department, title, story, kind) in enumerate(PERSONAS):
        supervisor, email, phone = SUPERVISORS[department]
        payload = {'user_id': uid, 'full_name': full_name, 'email': f'{uid}@example.com',
                   'phone': f'+1 202-555-{110 + index:04d}', 'job_title': title,
                   'supervisor_name': supervisor, 'supervisor_email': email, 'supervisor_phone': phone,
                   'employment_status': 'contractor' if uid == 'u009' else 'active',
                   'start_date': (hire if uid == 'u015' else start - timedelta(days=180)).isoformat(),
                   'location': 'Fictional Demo Office', 'contact_notes': 'Fictional demo contact; never call or email.'}
        call_at(db, datetime.combine(start, datetime.min.time()), employees.create, payload, db=db, user=admin)


def choose_cases(db, plan):
    chosen = {}
    for key, item in plan.items():
        days = set(item['days'])
        matches = [a for a in db.scalars(select(Alert).where(Alert.user_id == item['user_id']).order_by(Alert.start_time))
                   if a.start_time.date().isoformat() in days]
        if not matches:
            raise ValueError(f'No detected case for story {key}; generated scores must be fixed, never fabricated')
        chosen[key] = matches
    return chosen


def seed_cases(db, admin, analysts, selected):
    states = {
        'honey': (0, 'under_investigation', None), 'weekend': (None, 'open', None),
        'monthend': (2, 'closed', 'false_positive'), 'credential': (0, 'closed', 'true_positive'),
        'hoarding': (1, 'closed', 'true_positive'), 'probe': (2, 'closed', 'true_positive'),
        'repeat_bulk': (2, 'open', None), 'build_old': (0, 'closed', 'benign_explained'),
        'build_recent': (None, 'open', None), 'bulk': (None, 'open', None),
        'device': (1, 'under_investigation', None), 'replacement': (1, 'closed', 'benign_explained'),
        'slow': (0, 'closed', 'true_positive'), 'hire': (2, 'open', None),
    }
    notes = {
        'monthend': 'Approved month-end reporting caused this threshold alert; no unauthorized transfer was found.',
        'replacement': 'The approved laptop replacement and proposal restore explain the new device and download.',
        'build_old': 'The build engineer used an approved temporary build worker to restore large artifacts.',
    }
    for key, alerts in selected.items():
        index, state, outcome = states[key]
        for alert in alerts:
            if index is None:
                continue
            owner = analysts[index]
            start = alert.last_time + timedelta(hours=1)
            call_at(db, start, api.assign_alert, alert.id, api.AssignIn(owner=owner.username), db=db, admin=admin)
            call_at(db, start + timedelta(minutes=10), api.add_note, alert.id,
                    api.NoteIn(note=f'Reviewing evidence for {alert.user_id}, Case #{alert.id}; log context and ground truth are preserved.'), db=db, user=owner)
            if state in ('under_investigation', 'closed'):
                call_at(db, start + timedelta(minutes=20), api.update_alert, alert.id,
                        api.StatusIn(status='under_investigation'), db=db, user=owner)
            if state == 'closed':
                if key == 'probe':
                    call_at(db, start + timedelta(hours=1), api.update_alert, alert.id,
                            api.StatusIn(status='closed', outcome='false_positive', note='Initial review mistook the probing for an approved access check; this verdict was later corrected.'), db=db, user=owner)
                    call_at(db, start + timedelta(hours=2), api.update_alert, alert.id,
                            api.StatusIn(status='under_investigation', reason='Follow-up evidence confirms the access check was unauthorized.'), db=db, user=owner)
                call_at(db, start + timedelta(hours=3), api.update_alert, alert.id,
                        api.StatusIn(status='closed', outcome=outcome,
                                     note=notes.get(key, f'Confirmed unauthorized activity in the labelled scenario for {alert.user_id}; evidence supports a true positive.')), db=db, user=owner)


def seed_escalations(db, admin, selected):
    plan = [('credential', 'submitted'), ('hoarding', 'acknowledged'), ('probe', 'needs_info'),
            ('replacement', 'contacted'), ('slow', 'completed'), ('monthend', 'withdrawn')]
    result = {}
    for key, target in plan:
        alert = selected[key][0]
        assignment = db.scalar(select(AlertAssignment).where(AlertAssignment.alert_id == alert.id))
        owner = db.scalar(select(User).where(User.username == assignment.owner))
        base = alert.last_time + timedelta(hours=8)
        created = call_at(db, base, escalations.create,
                          escalations.Filing(alert_id=alert.id, summary=f'Request administrative review of the documented evidence for Case #{alert.id}.',
                                             recommendation='contact_user' if key == 'replacement' else 'access_review', priority='urgent' if key == 'credential' else 'normal'), db=db, user=owner)
        eid = created['id']; result[target] = eid
        if target == 'withdrawn':
            call_at(db, base + timedelta(hours=1), escalations.withdraw, eid, db=db, user=owner)
        elif target != 'submitted':
            call_at(db, base + timedelta(minutes=30), escalations.acknowledge, eid, db=db, user=admin)
            if target == 'needs_info':
                call_at(db, base + timedelta(hours=1), escalations.request_info, eid, escalations.MessageInput(message='Please identify the relevant restricted-resource evidence.'), db=db, user=admin)
                call_at(db, base + timedelta(hours=2), escalations.message, eid, escalations.MessageInput(message='The case contains repeated denials followed by successful restricted access.'), db=db, user=owner)
                call_at(db, base + timedelta(hours=3), escalations.request_info, eid, escalations.MessageInput(message='Please attach the follow-up access-review context before handling.'), db=db, user=admin)
            elif target in ('contacted', 'completed'):
                call_at(db, base + timedelta(hours=1), escalations.contacted, eid,
                        escalations.ContactInput(contact_method='in_person', summary='Fictional contact record: reviewed the case context with the demo employee and supervisor.'), db=db, user=admin)
                if target == 'completed':
                    call_at(db, base + timedelta(hours=2), escalations.complete, eid,
                            escalations.CompleteInput(handling_note='Administrative review and contact are complete; the advisory follow-up has been recorded.'), db=db, user=admin)
    return result


def seed_notifications(db, cutoff):
    db.info['notifications_silent'] = False
    # Replay only a small selection of real historical events into the central
    # publishers; receipts retain the exact event ID used by normal app delivery.
    candidates = db.scalars(select(CaseEvent).where(CaseEvent.action.in_(['assigned', 'resolved', 'reopened'])).order_by(CaseEvent.created_at, CaseEvent.id)).all()
    by_owner = {}
    for event in candidates:
        if event.action == 'assigned': by_owner.setdefault(event.detail['to'], []).append(event)
    selected = [e for events in by_owner.values() for e in events[-3:]]
    selected += [e for e in candidates if e.action == 'resolved'][-3:]
    selected += [e for e in candidates if e.action == 'reopened']
    deliveries = [(event.created_at, 'case', event) for event in selected]
    deliveries += [(event.created_at, 'escalation', event) for event in db.scalars(select(EscalationEvent).where(EscalationEvent.action.in_(['submitted', 'acknowledge_escalation', 'request_escalation_info', 'contact_escalation', 'complete_escalation']))) ]
    for index, (_, kind, event) in enumerate(sorted(deliveries, key=lambda row: (row[0], row[1], row[2].id))):
        delivery_time = cutoff - timedelta(hours=4) + timedelta(minutes=index)
        if kind == 'case': call_at(db, delivery_time, notifications.case_event, db, db.get(Alert, event.alert_id), event)
        else: call_at(db, delivery_time, notifications.escalation_event, db, db.get(Escalation, event.escalation_id), event)
    # Treat delivery at the demo checkpoint as a historical review inbox, so the
    # 30-day retention policy does not erase old-scene examples on first login.
    for user in db.scalars(select(User)):
        rows = db.scalars(select(Notification).where(Notification.recipient == user.username).order_by(Notification.id)).all()
        for index, row in enumerate(rows):
            if index < len(rows) - 2:
                call_at(db, cutoff - timedelta(hours=1), notifications.mark_read, row.id, db=db, user=user)
    audit(db, 'demo_seed', 'prepare_demo_inbox', detail={'historical_delivery': True})
    db.commit()


def build_demo(db, *, seed=7, days=60, end=None, with_ai=False, guide_path=DEFAULT_GUIDE):
    end = end or default_end()
    cutoff = datetime.combine(end, datetime.min.time())
    if db.scalar(select(Subject.user_id).limit(1)) or db.scalar(select(User.id).limit(1)):
        raise ValueError('Demo seed requires an empty database. Choose --reset to replace the active database.')
    events, honeytokens, plan = generate_demo(seed, days, end)
    start = end - timedelta(days=days - 1)
    pipeline.seed_rule_config(db)
    admin, analysts, credentials = seed_accounts(db, datetime.combine(start - timedelta(days=1), datetime.min.time()))
    for honey in honeytokens:
        db.add(Honeytoken(**honey, created_by=admin.username, created_at=datetime.combine(start, datetime.min.time())))
        audit(db, admin, 'create_honeytoken', honey['resource'], {'demo': True})
    db.commit()
    imported = pipeline.ingest_records(db, events, 'demo')
    audit(db, admin, 'ingest_demo_events', detail={'accepted': imported['accepted'], 'rejected': imported['rejected']})
    if imported['rejected']:
        raise ValueError(f"Importer rejected {imported['rejected']} rows: {imported['errors']}")
    with clock(cutoff):
        pipeline.reprocess_users(db, silent=True)
    for event in db.scalars(select(Event)):
        event.ingested_at = cutoff
    for alert in db.scalars(select(Alert)):
        alert.created_at = alert.last_time + timedelta(minutes=5)
    seed_profiles(db, admin, start, end - timedelta(days=10))
    selected = choose_cases(db, plan)
    db.info['notifications_silent'] = True
    seed_cases(db, admin, analysts, selected)
    escalation_ids = seed_escalations(db, admin, selected)
    seed_notifications(db, cutoff)
    if with_ai and ai.ai_configured():
        for alert in db.scalars(select(Alert).where(Alert.category.in_(['High', 'Critical'])).order_by(Alert.id)):
            owner_name = cases.get_owner(db, alert.id)
            if owner_name:
                owner = db.scalar(select(User).where(User.username == owner_name))
                call_at(db, cutoff, api.explain, alert.id, db=db, user=owner)
            else:
                call_at(db, cutoff, ai.explain_alert, db, alert)
    with clock(cutoff):
        metrics = evaluation.run_evaluation(db, run_by='demo_seed')
    audit(db, admin, 'run_demo_evaluation')
    for row in db.scalars(select(EvaluationRun)):
        row.created_at = cutoff
    for row in db.scalars(select(AuditLog)):
        if row.timestamp > cutoff:
            row.timestamp = cutoff
    manifest = {'seed': seed, 'days': days, 'end': end.isoformat(), 'cutoff': cutoff.isoformat(),
                'event_count': len(events), 'event_sha256': hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest(),
                'stories': plan, 'story_cases': {key: [a.id for a in rows] for key, rows in selected.items()},
                'escalation_ids': escalation_ids, 'reopened_case': selected['probe'][0].id,
                'expected_workflows': workflow_snapshot(db), 'import_rejected': imported['rejected']}
    db.add(DemoSeedRun(created_at=cutoff, manifest=manifest))
    audit(db, admin, 'seed_demo', detail={'seed': seed, 'days': days, 'events': len(events)})
    db.flush()
    for row in db.scalars(select(AuditLog).where(AuditLog.timestamp > cutoff)):
        row.timestamp = cutoff
    db.commit()
    problems = verify_demo(db)
    if problems:
        raise ValueError('Demo verification failed:\n' + '\n'.join(f'- {p}' for p in problems))
    guide = render_guide(db, credentials, metrics)
    if guide_path:
        guide_path = Path(guide_path); guide_path.parent.mkdir(parents=True, exist_ok=True); guide_path.write_text(guide, encoding='utf-8')
    return summary(db), guide


def summary(db):
    risks = pipeline.current_risk(db)
    return {'users': db.scalar(select(func.count()).select_from(Subject)), 'events': db.scalar(select(func.count()).select_from(Event)),
            'alerts': db.scalar(select(func.count()).select_from(Alert)),
            'alerts_by_category': dict(Counter(a.category for a in db.scalars(select(Alert)))),
            'cases_by_state': dict(Counter(a.status for a in db.scalars(select(Alert)))),
            'current_risk': dict(Counter(risks.get(s.user_id, {}).get('category', 'Low') for s in db.scalars(select(Subject)))),
            'escalations': dict(Counter(e.status for e in db.scalars(select(Escalation)))),
            'unread': {u.username: db.scalar(select(func.count()).select_from(Notification).where(Notification.recipient == u.username, Notification.read_at.is_(None))) for u in db.scalars(select(User).order_by(User.id))}}


def verify_demo(db):
    """Collect every inconsistency; used both after creation and by --verify-only."""
    problems = []
    run = db.scalar(select(DemoSeedRun).order_by(DemoSeedRun.id.desc()))
    if not run:
        return ['No demo manifest found; select the demo seed before using --verify-only.']
    m = run.manifest
    cutoff = datetime.fromisoformat(m['cutoff'])
    subjects = {s.user_id: s for s in db.scalars(select(Subject))}
    profiles = {p.user_id: p for p in db.scalars(select(EmployeeProfile))}
    expected_ids = {p[0] for p in PERSONAS}
    if set(subjects) != expected_ids: problems.append('Expected exactly 15 subjects u001–u015; u016 must remain absent.')
    if set(profiles) != expected_ids: problems.append('Expected exactly 15 profiles u001–u015; u016 must remain unregistered.')
    if Counter(s.department for s in subjects.values()) != Counter({d: 3 for d in SUPERVISORS}): problems.append('Expected three logged users per department.')
    for uid in expected_ids:
        s, p = subjects.get(uid), profiles.get(uid)
        if not s or not p: continue
        if not db.scalar(select(Event.id).where(Event.user_id == uid).limit(1)): problems.append(f'{uid} has no events.')
        departments = set(db.scalars(select(Event.department).where(Event.user_id == uid).distinct()))
        if departments != {s.department}: problems.append(f'{uid} log/Subject departments disagree.')
        if s.department != next(person[2] for person in PERSONAS if person[0] == uid): problems.append(f'{uid} department differs from the declared persona.')
        if p.job_title != next(person[3] for person in PERSONAS if person[0] == uid): problems.append(f'{uid} profile job does not match its department/persona.')
        if (p.supervisor_name, p.supervisor_email, p.supervisor_phone) != SUPERVISORS.get(s.department): problems.append(f'{uid} has an inconsistent supervisor.')
        if not p.email.endswith('@example.com') or not p.supervisor_email.endswith('@example.com'): problems.append(f'{uid} has a non-fictional email domain.')
        if p.full_name in [v[0] for v in SUPERVISORS.values()]: problems.append(f'{uid} is also listed as a supervisor.')
        baseline = db.get(Baseline, uid)
        expected_baseline = 'pending' if uid == 'u015' else 'established'
        if s.baseline_status != expected_baseline or not baseline or baseline.status != expected_baseline: problems.append(f'{uid} baseline must be {expected_baseline}.')
    if db.scalar(select(func.count()).select_from(ParseError)) or m['import_rejected']: problems.append('Importer parse errors/rejections exist.')
    if db.scalar(select(func.count()).select_from(Event)) != m['event_count']: problems.append('Event count changed from the imported demo.')
    if db.scalar(select(Event.id).where(Event.label_malicious.is_(True), Event.timestamp < datetime.fromisoformat(m['end']) - timedelta(days=m['days'] - 15)).limit(1)):
        problems.append('Malicious activity occurs during the first fourteen calendar days.')
    if not 20000 <= m['event_count'] <= 30000: problems.append('Event volume must be roughly 20,000–30,000.')
    users = {u.username: u for u in db.scalars(select(User))}
    owners = cases.owners_for(db, db.scalars(select(Alert.id)))
    resolutions_now = resolutions.current_for(db, db.scalars(select(Alert.id)))
    for a in db.scalars(select(Alert)):
        owner = owners.get(a.id)
        if owner and (owner.owner not in users or users[owner.owner].role != 'analyst'): problems.append(f'Case #{a.id} has an invalid owner.')
        if owner and owner.assigned_at < a.start_time: problems.append(f'Case #{a.id} was assigned before it started.')
        if a.status not in ('open', 'under_investigation', 'closed'): problems.append(f'Case #{a.id} has a fourth case status.')
        truth = bool(db.scalar(select(Event.id).where(Event.user_id == a.user_id, Event.timestamp >= a.start_time - timedelta(hours=1), Event.timestamp <= a.last_time + timedelta(hours=1), Event.label_malicious.is_(True)).limit(1)))
        if a.status == 'closed':
            verdict = resolutions_now.get(a.id)
            if not verdict or len(verdict.note.strip()) < 15: problems.append(f'Closed Case #{a.id} lacks an outcome/closing note.')
            elif (verdict.outcome == 'true_positive') != truth: problems.append(f'Case #{a.id} current outcome disagrees with ground truth.')
        history = db.scalars(select(AlertResolution).where(AlertResolution.alert_id == a.id).order_by(AlertResolution.id)).all()
        for verdict in history:
            if not owner or verdict.resolved_by != owner.owner or verdict.resolved_at < owner.assigned_at: problems.append(f'Case #{a.id} resolution precedes assignment or has the wrong owner.')
            if verdict.reopened_at and verdict.reopened_at <= verdict.resolved_at: problems.append(f'Case #{a.id} reopening precedes closure.')
            if verdict.outcome == 'false_positive' and truth and a.id != m['reopened_case']: problems.append(f'Case #{a.id} has an unexplained historical false-positive verdict on an attack.')
        events = db.scalars(select(CaseEvent).where(CaseEvent.alert_id == a.id).order_by(CaseEvent.id)).all()
        if any(x.created_at > y.created_at for x, y in zip(events, events[1:])): problems.append(f'Case #{a.id} event timestamps are not ordered.')
        state = 'open'
        for event in events:
            if event.created_at < a.start_time: problems.append(f'Case #{a.id} has an event before the incident.')
            if event.action == 'status_changed':
                if event.detail.get('from') != state: problems.append(f'Case #{a.id} has an invalid status transition.')
                state = event.detail.get('to')
        if state != a.status: problems.append(f'Case #{a.id} status does not match its timeline.')
    states = set(db.scalars(select(Escalation.status)))
    if states != set(escalations.STATUSES): problems.append('Escalations do not cover all six statuses.')
    for e in db.scalars(select(Escalation)):
        a = db.get(Alert, e.alert_id); owner = owners.get(e.alert_id)
        if not a or not owner or owner.owner != e.created_by or e.user_id != a.user_id or e.user_id not in profiles: problems.append(f'Escalation #{e.id} has inconsistent case ownership/profile references.')
        if e.snapshot.get('peak_score') != (a.peak_score if a else None) or e.snapshot.get('filed_at') != e.created_at.isoformat(): problems.append(f'Escalation #{e.id} snapshot is inconsistent.')
        contacts = db.scalars(select(EmployeeContact).where(EmployeeContact.escalation_id == e.id)).all()
        if e.status in ('contacted', 'completed') and not contacts: problems.append(f'Escalation #{e.id} lacks contact history.')
        if any(c.user_id != e.user_id or c.contacted_by != e.handled_by or c.created_at < e.created_at for c in contacts): problems.append(f'Escalation #{e.id} contact history is inconsistent.')
        if e.status == 'completed' and (not e.completed_at or len(e.handling_note or '') < 10): problems.append(f'Escalation #{e.id} lacks completion information.')
        if e.handled_by and (e.handled_by not in users or users[e.handled_by].role != 'admin'): problems.append(f'Escalation #{e.id} has an invalid handling administrator.')
    reopened = db.scalars(select(AlertResolution).where(AlertResolution.alert_id == m['reopened_case']).order_by(AlertResolution.id)).all()
    if len(reopened) != 2 or [r.outcome for r in reopened] != ['false_positive', 'true_positive'] or not reopened[0].reopened_at:
        problems.append('The documented reopened case must preserve its false-positive then true-positive resolution history.')
    honey = db.get(Alert, m['story_cases']['honey'][0])
    if not honey or honey.peak_score != 50: problems.append('The isolated honeytoken case must score exactly 50.')
    # Delivery provenance survives reads/dismissals in the notification receipt table.
    for n in db.scalars(select(Notification)):
        receipts = db.scalars(select(NotificationReceipt).where(NotificationReceipt.recipient == n.recipient, NotificationReceipt.type == n.type)).all()
        linked_alert = db.get(Alert, n.alert_id) if n.alert_id else None
        valid = bool(n.type in ('alert_new', 'alert_unassigned_24h') and linked_alert
                     and linked_alert.category in ('High', 'Critical') and n.recipient in users and users[n.recipient].role == 'admin')
        for receipt in receipts:
            if valid: break
            kind, _, value = receipt.delivery_key.partition(':')
            if not value.isdigit(): continue
            event = db.get(CaseEvent if kind == 'case_event' else EscalationEvent, int(value))
            if event and ((kind == 'case_event' and event.alert_id == n.alert_id) or (kind == 'escalation_event' and event.escalation_id == n.escalation_id)):
                if n.type == 'case_assigned': valid = event.detail.get('to') == n.recipient
                elif n.type.startswith('escalation_') and n.type not in ('escalation_submitted', 'escalation_reply', 'escalation_withdrawn'):
                    escalation = db.get(Escalation, n.escalation_id)
                    valid = bool(escalation and escalation.created_by == n.recipient)
                else: valid = n.recipient in users and users[n.recipient].role == 'admin'
                if valid: break
        if not valid or n.recipient not in users: problems.append(f'Notification #{n.id} has no corresponding real workflow event/recipient.')
        if n.read_at and n.read_at < n.created_at: problems.append(f'Notification #{n.id} was read before delivery.')
    for model in Base.registry.mappers:
        cls = model.class_
        for column in cls.__table__.columns:
            if not isinstance(column.type, DateTime): continue
            if db.scalar(select(func.count()).select_from(cls).where(getattr(cls, column.name) > utcnow())):
                problems.append(f'Future timestamp(s) in {cls.__tablename__}.{column.name}.')
    risk = summary(db)['current_risk']
    if any(risk.get(category, 0) < minimum for category, minimum in [('Critical', 1), ('High', 2), ('Medium', 2)]): problems.append(f'Current risk spread is insufficient: {risk}.')
    actual = workflow_snapshot(db)
    for key, expected in m['expected_workflows'].items():
        if actual[key] != expected: problems.append(f'{key} differ from the expected demo transitions/state.')
    with clock(cutoff):
        pipeline.reprocess_users(db, silent=True)
    after = workflow_snapshot(db)
    if after != actual: problems.append('Second recompute changed alert counts, ownership, resolutions, escalations or workflow history.')
    stored = db.scalar(select(EvaluationRun).order_by(EvaluationRun.id.desc()))
    with clock(cutoff):
        metrics = evaluation.run_evaluation(db, run_by='demo_verify', store=False)
    if 'error' in metrics or not stored or stored.results.get('modes') != metrics.get('modes'): problems.append('Stored evaluation is absent or disagrees with recomputed metrics.')
    problems.extend(verify_privacy(db, users, profiles, cutoff))
    return problems


def verify_privacy(db, users, profiles, cutoff):
    from fastapi.testclient import TestClient
    from .main import app
    markers = {getattr(p, field) for p in profiles.values() for field in ('full_name', 'email', 'phone', 'supervisor_name', 'supervisor_email', 'supervisor_phone') if getattr(p, field)}
    paths = ['/api/users', '/api/users/stats', '/api/dashboard/summary', '/api/alerts?limit=1000', '/api/my-cases',
             '/api/escalations', '/api/escalations/summary', '/api/notifications?limit=100', '/api/notifications/unread-count',
             '/api/reports/risk', '/api/reports/risk?format=csv', '/api/reports/indicators', '/api/reports/range',
             '/api/evaluation/results', '/api/evaluation/feedback', '/api/honeytokens', '/api/rules', '/api/mitre/mapping', '/api/auth/me']
    paths += [f'/api/users/{uid}/{suffix}' for uid in sorted(profiles) for suffix in ('overview', 'risk', 'timeline', 'activity')]
    paths += [f'/api/alerts/{aid}{suffix}' for aid in db.scalars(select(Alert.id)) for suffix in ('', '/events')]
    paths += [f'/api/escalations/{eid}' for eid in db.scalars(select(Escalation.id))]
    problems = []
    old_db = app.dependency_overrides.get(get_db)
    old_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        for analyst in [u for u in users.values() if u.role == 'analyst']:
            app.dependency_overrides[get_current_user] = lambda: analyst
            for path in paths:
                with clock(cutoff):
                    response = client.get(path)
                if response.status_code not in (200, 403, 404): problems.append(f'Analyst endpoint {path} failed: {response.status_code}.')
                if any(marker in response.text for marker in markers): problems.append(f'Personal data leaked at {path}.')
        # View audit defaults are wall-clock values; keep the seed checkpoint deterministic.
        for row in db.scalars(select(AuditLog).where(AuditLog.timestamp > cutoff)):
            row.timestamp = cutoff
        db.commit()
    finally:
        for dep, old in ((get_db, old_db), (get_current_user, old_user)):
            if old is None: app.dependency_overrides.pop(dep, None)
            else: app.dependency_overrides[dep] = old
    return problems


def render_guide(db, credentials, metrics):
    run = db.scalar(select(DemoSeedRun).order_by(DemoSeedRun.id.desc()))
    m = run.manifest; stats = summary(db)
    stats['unread'] = {u.username: db.scalar(select(func.count()).select_from(Notification).where(
        Notification.recipient == u.username, Notification.read_at.is_(None), Notification.type != 'alert_unassigned_24h'))
        for u in db.scalars(select(User).order_by(User.id))}
    owners = cases.owners_for(db, db.scalars(select(Alert.id))); verdicts = resolutions.current_for(db, db.scalars(select(Alert.id)))
    lines = ['# InsiderGuard: 15-user demonstration guide', '', f"Generated from seed **{m['seed']}**, {m['days']} days, ending **{m['end']} at 00:00 UTC**.",
             'All names and supervisors are fictional, emails use example.com, and phones use the reserved fictional 202-555-01xx range. Never call or email them.',
             'Only one seed is active in a database. `--reset` irreversibly replaces the selected database. Run verification before making live demo changes.', '',
             '## Accounts (demo credentials only)', '', '| Account | Role | Password |', '|---|---|---|']
    for user in db.scalars(select(User).order_by(User.id)):
        lines.append(f'| {user.username} | {user.role} | {credentials[user.username]} |')
    lines += ['', 'Environment-configured admin/primary analyst credentials above are from this actual run. Do not use production credentials to generate a publicly shared guide.', '',
              '## Personas and actual cases', '', '| User ID | Fictional name | Department | Story | Actual alerts (peak) | Case state | Owner | Outcome |', '|---|---|---|---|---|---|---|---|']
    for uid, name, dept, title, story, kind in PERSONAS:
        alerts = db.scalars(select(Alert).where(Alert.user_id == uid).order_by(Alert.start_time)).all()
        lines.append(f"| {uid} | {name} | {dept} | {title}: {story} | " + '; '.join(f'Case #{a.id} ({a.peak_score:g}, {a.category})' for a in alerts) + ' | ' + '; '.join(a.status for a in alerts) + ' | ' + '; '.join(owners[a.id].owner if a.id in owners else 'Unassigned' for a in alerts) + ' | ' + '; '.join(verdicts[a.id].outcome if a.id in verdicts else '—' for a in alerts) + ' |')
    lines += ['', f"Case #{m['reopened_case']} is the documented exception: an initial false-positive verdict was corrected after reopening; its current outcome is true positive. u008 has a later, separate bulk incident.",
              'u005 has a seven-calendar-day holiday with no events. u015 started ten days before the cutoff and has a pending baseline: its large legitimate download is a rule alert, not an anomaly.',
              'u016 has neither logs nor a profile; create a pre-registered profile for it live. Profiles have no department column; the UI obtains department only from logs.', '',
              '## Expected numbers from this run', '', '```json', json.dumps(stats, indent=2, sort_keys=True), '```', '',
              '| Evaluation mode | Precision | Recall | F1 |', '|---|---:|---:|---:|']
    for mode, metric in metrics['modes'].items():
        lines.append(f"| {mode} | {metric['precision']:.4f} | {metric['recall']:.4f} | {metric['f1']:.4f} |")
    lines += ['', 'The honeytoken fix removes double counting of a registered decoy as a novel resource category. A normal-hour, otherwise isolated touch now scores 50 rather than 68. Both seeds and their evaluation metrics are affected.', '',
              '## Escalations', '', '| Status | Escalation | Case |', '|---|---|---|']
    for e in db.scalars(select(Escalation).order_by(Escalation.id)):
        lines.append(f'| {e.status} | Escalation #{e.id} | Case #{e.alert_id} |')
    critical = m['story_cases']['bulk'][0]; claimable = m['story_cases']['weekend'][0]
    lines += ['', '## Ten-minute walkthrough', '',
              f'1. **0:00–1:00, admin:** open Alerts, filter Owner = Unassigned, and assign current Critical Case #{critical} (u010) to an analyst. Explain that Owner is separate from the three case statuses.',
              f'2. **1:00–3:00, analyst:** claim unassigned Case #{claimable} (u002), open My cases, move to Under investigation, add a note, then close as true positive with a meaningful closing note. Escalate it to admin with an advisory recommendation.',
              '3. **3:00–4:30, admin:** open that escalation, acknowledge it, follow View user profile and contact details, and inspect Personal information. Log contact on the escalation; check the linked private Contact log entry. Mark as handled with a note.',
              '4. **4:30–5:00, both roles:** use the bell to see role-specific updates; mark read/unread and show Back to Notifications. There is no dropdown and no personal data in notification text.',
              '5. **5:00–6:30:** open Users, compare departments/risk/activity charts, open u015 to explain cold start, and u014 to explain legitimate on-call activity. Analysts cannot see personal information or contact logs.',
              f'6. **6:30–7:00:** inspect Case #{m["reopened_case"]} history and its two resolutions; show u008’s separate later incident. Use breadcrumbs and Back to return to a filtered Alerts view.',
              '7. **7:00–8:00:** show Evaluation lab metrics separately from Operational feedback (analyst verdicts). Analyst verdicts do not establish recall or F1.',
              '8. **8:00–9:00:** use Reports Owner and Outcome filters, outcome chart, and CSV export.',
              '9. **9:00–10:00, admin:** Users → Add employee profile → u016, demonstrating pre-registration without log activity. Its department is read-only and absent until logs arrive.', '',
              '## Reproducibility and safety', '',
              f'`python -m app.seed_demo --reset --seed {m["seed"]} --days {m["days"]} --end {m["end"]}`',
              '`python -m app.seed_demo --verify-only`',
              'Supported durations are 45–120 days. The midnight end-day cutoff prevents future observed events even on a Friday. The same seed/end/duration produces identical telemetry, workflow IDs, report text and metrics; salted password hashes and runtime durations are not deterministic artifacts.',
              'History is created silently via application endpoints/services, with backdated timestamps. A small inbox is delivered at the final checkpoint from real historical case/escalation event hooks (mostly read, two unread per account); it is a demonstration replay, not a claim that email or other external notifications were sent.',
              'Unread numbers above describe the seeded inbox. Opening the admin bell can additionally create the normal once-per-alert reminders for High/Critical cases that have remained unassigned for 24 real hours; those runtime reminders depend on when the demonstration is opened and do not change the prepared case state.',
              'AI narratives are never fabricated. Without --with-ai, no network call is made. With --with-ai and a configured key, real explanations may vary and network access is required.',
              f'Event SHA-256: `{m["event_sha256"]}`', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset', action='store_true', help='wipe the selected database and replace it with the demo')
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--days', type=int, default=60)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--with-ai', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    if args.verify_only and args.reset:
        parser.error('--verify-only cannot be combined with --reset')
    # Validate generation arguments before any destructive operation.
    if not args.verify_only:
        generate_demo(args.seed, args.days, args.end)
    if args.reset:
        Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        try:
            if args.verify_only:
                problems = verify_demo(db)
                if problems: raise ValueError('\n'.join(f'- {p}' for p in problems))
                stats = summary(db)
            else:
                stats, guide = build_demo(db, seed=args.seed, days=args.days, end=args.end, with_ai=args.with_ai)
            print(json.dumps(stats, indent=2, sort_keys=True))
            metric = db.scalar(select(EvaluationRun).order_by(EvaluationRun.id.desc()))
            if metric:
                for mode, values in metric.results['modes'].items():
                    print(f"{mode:13s} P={values['precision']:.4f} R={values['recall']:.4f} F1={values['f1']:.4f}")
            manifest = db.scalar(select(DemoSeedRun).order_by(DemoSeedRun.id.desc())).manifest
            print(f"Cheat sheet: assign Critical Case #{manifest['story_cases']['bulk'][0]}; claim Case #{manifest['story_cases']['weekend'][0]}; reopened history Case #{manifest['reopened_case']}; new hire u015; register u016.")
            print(f'Guide: {DEFAULT_GUIDE}')
            print('\033[92mPASS: demo verification passed (all consistency checks).\033[0m')
        except (ValueError, RuntimeError) as error:
            db.rollback()
            print(f'FAIL: {error}')
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
