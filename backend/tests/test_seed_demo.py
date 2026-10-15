import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.demo_dataset import PERSONAS, default_end, generate_demo
from app.models import Alert, AlertAssignment, AlertResolution, CaseEvent, Detection, DemoSeedRun, EmployeeProfile, Event, Notification, Subject
from app.seed_demo import build_demo, verify_demo, workflow_snapshot


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    folder = tmp_path_factory.mktemp('verified_demo')
    path = folder / 'demo.db'
    engine = create_engine(f'sqlite:///{path}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as db:
        with patch('app.ai.generate_explanation', side_effect=AssertionError('Default demo must not call AI')):
            stats, guide = build_demo(db, seed=7, days=60, end=date(2026, 10, 9), guide_path=folder / 'GUIDE.md')
    yield engine, path, stats, guide
    engine.dispose()


def test_demo_verifies_real_workflows_profiles_risk_and_cold_start(demo):
    engine, path, stats, guide = demo
    assert stats['users'] == 15 and 20000 <= stats['events'] <= 30000
    assert stats['current_risk'] == {'Low': 9, 'Medium': 2, 'High': 3, 'Critical': 1}
    assert set(stats['cases_by_state']) == {'open', 'under_investigation', 'closed'}
    assert set(stats['escalations']) == {'submitted', 'acknowledged', 'needs_info', 'contacted', 'completed', 'withdrawn'}
    assert all(0 < count <= 3 for count in stats['unread'].values())
    with Session(engine, autoflush=False) as db:
        assert verify_demo(db) == []
        assert set(db.scalars(select(Subject.user_id))) == {p[0] for p in PERSONAS}
        assert len(db.scalars(select(EmployeeProfile)).all()) == 15
        assert not db.scalar(select(Detection.id).where(Detection.user_id == 'u015', Detection.source == 'anomaly'))
        manifest = db.scalar(select(DemoSeedRun)).manifest
        reopened = db.scalars(select(AlertResolution).where(AlertResolution.alert_id == manifest['reopened_case']).order_by(AlertResolution.id)).all()
        assert [r.outcome for r in reopened] == ['false_positive', 'true_positive'] and reopened[0].reopened_at
        critical = db.get(Alert, manifest['story_cases']['bulk'][0])
        assert critical.category == 'Critical' and not db.scalar(select(AlertAssignment.id).where(AlertAssignment.alert_id == critical.id))
        assert 'Case #' + str(critical.id) in guide and 'DemoReview#23456' in guide
        assert '2026-10-09' in guide and '0.8667' in guide


def test_same_seed_end_has_identical_events_workflows_guide_and_metrics(demo, tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "second.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        stats, guide = build_demo(db, seed=7, days=60, end=date(2026, 10, 9), guide_path=None)
        with Session(demo[0]) as first:
            assert workflow_snapshot(db) == workflow_snapshot(first)
        assert stats == demo[2] and guide == demo[3]
    engine.dispose()


def test_verifier_lists_multiple_independent_problems(demo, tmp_path):
    copy = tmp_path / 'broken.db'
    with sqlite3.connect(demo[1]) as source, sqlite3.connect(copy) as target:
        source.backup(target)
    engine = create_engine(f'sqlite:///{copy}', connect_args={'check_same_thread': False})
    with Session(engine, autoflush=False) as db:
        db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == 'u001')).supervisor_email = 'wrong@example.com'
        db.scalar(select(AlertResolution)).note = 'short'
        db.commit()
        problems = verify_demo(db)
        assert any('supervisor' in problem for problem in problems)
        assert any('closing note' in problem for problem in problems)
        assert any('resolutions differ' in problem for problem in problems)
    engine.dispose()


def test_cli_verify_only_and_original_seed_smoke(demo, tmp_path):
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{demo[1]}'}
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'app.seed_demo', '--verify-only'], cwd=backend, env=env, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS: demo verification passed' in result.stdout
    env['DATABASE_URL'] = f'sqlite:///{tmp_path / "original.db"}'
    result = subprocess.run([sys.executable, '-m', 'app.seed', '--reset', '--users', '15', '--days', '49'], cwd=backend, env=env, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'rejected=0' in result.stdout and 'hybrid' in result.stdout


def test_event_format_dates_labels_and_repeat_offender_are_deterministic():
    from app.generator import FIELDS
    end = date(2026, 10, 9)
    first = generate_demo(seed=7, days=60, end=end)
    second = generate_demo(seed=7, days=60, end=end)
    assert first == second
    events, honeytokens, plan = first
    assert all(set(event) == set(FIELDS) for event in events)
    assert max(datetime.fromisoformat(e['timestamp']) for e in events) == datetime(2026, 10, 9)
    earliest = min(datetime.fromisoformat(e['timestamp']) for e in events)
    assert all(datetime.fromisoformat(e['timestamp']) >= earliest + timedelta(days=14) for e in events if e['label_malicious'])
    assert len(plan['slow']['days']) == 5
    assert plan['probe']['user_id'] == plan['repeat_bulk']['user_id'] == 'u008'
    assert default_end(date(2026, 10, 15)) == date(2026, 10, 9)
    assert default_end(date(2026, 10, 9)) == date(2026, 10, 9)
    short, _, _ = generate_demo(seed=3, days=45, end=date(2026, 3, 30))
    earliest = min(datetime.fromisoformat(e['timestamp']) for e in short)
    assert all(datetime.fromisoformat(e['timestamp']) >= earliest + timedelta(days=14) for e in short if e['label_malicious'])


def test_seed_refuses_existing_database_or_invalid_dates_without_wiping(demo):
    with Session(demo[0], autoflush=False) as db:
        with pytest.raises(ValueError, match='empty database'):
            build_demo(db, guide_path=None)
    with pytest.raises(ValueError, match='future'):
        generate_demo(end=date.today() + timedelta(days=2))
    with pytest.raises(ValueError, match='45 and 120'):
        generate_demo(days=20)
