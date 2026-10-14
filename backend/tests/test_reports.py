import csv
import io
from datetime import datetime, timezone

import pytest

from app.models import Alert, Event, Subject
from test_accounts import account_env


@pytest.fixture
def report_env(account_env):
    client, admin, analyst, _, sessions = account_env
    records = [
        (1, 'u1', '2026-10-01T12:00:00', 20, 'Low', 'open', ['download']),
        (2, 'u1', '2026-10-02T23:59:59.999999', 80, 'High', 'open', ['download', 'decoy']),
        (3, 'u2', '2026-10-02T18:00:00', 95, 'Critical', 'under_investigation', ['decoy']),
        (4, 'u2', '2026-10-03T00:00:00', 55, 'Medium', 'closed', ['denied']),
        (5, 'u3', '2026-10-02T00:00:00', 60, 'Medium', 'closed', ['download']),
        (6, 'u1', '2026-10-04T12:00:00', 75, 'High', 'under_investigation', []),
    ]
    with sessions() as db:
        for uid, department in [('u1', 'Finance'), ('u2', 'IT'), ('u3', 'Finance')]:
            db.add(Subject(user_id=uid, department=department, baseline_status='established'))
        for aid, uid, timestamp, score, category, status, indicators in records:
            when = datetime.fromisoformat(timestamp)
            db.add(Alert(id=aid, user_id=uid, start_time=when, last_time=when, peak_score=score, category=category, status=status,
                         breakdown=[{'name': name, 'weight': 10} for name in indicators]))
            db.add(Event(user_id=uid, timestamp=when, department='IT' if uid == 'u2' else 'Finance', event_type='auth'))
        db.commit()
    return client, admin, analyst


def report(env, params=None):
    client, _, analyst = env
    response = client.get('/api/reports/risk', headers=analyst, params=params or {})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('params,expected', [
    ({'start': '2026-10-03'}, {4, 6}), ({'end': '2026-10-01'}, {1}),
    ({'department': 'Finance'}, {1, 2, 5, 6}), ({'category': 'High'}, {2, 6}),
    ({'category': 'Low, Critical'}, {1, 3}), ({'status': 'open,closed'}, {1, 2, 4, 5}),
    ({'min_score': 80}, {2, 3}), ({'max_score': 60}, {1, 4, 5}),
    ({'user_id': 'u1'}, {1, 2, 6}), ({'indicator': 'decoy'}, {2, 3}),
    ({'indicator': 'unknown'}, set()),
])
def test_report_filters(report_env, params, expected):
    assert {row['alert_id'] for row in report(report_env, params)['alerts']} == expected


def test_combined_filters_end_date_and_event_coverage(report_env):
    params = {'start': '2026-10-02', 'end': '2026-10-02', 'department': 'Finance', 'category': 'High,Medium',
              'status': 'open,closed', 'min_score': 60, 'max_score': 85, 'user_id': 'u1', 'indicator': 'download'}
    result = report(report_env, params)
    assert [row['alert_id'] for row in result['alerts']] == [2]
    assert result['coverage']['events_analysed'] == 1
    assert result['coverage']['users_monitored'] == 1
    assert result['filters']['end'] == '2026-10-02'
    day = report(report_env, {'start': '2026-10-02', 'end': '2026-10-02'})
    assert {row['alert_id'] for row in day['alerts']} == {2, 3, 5}
    assert day['coverage']['events_analysed'] == 3


@pytest.mark.parametrize('params', [
    {'category': 'Unknown'}, {'category': 'High,'}, {'category': ''}, {'status': 'pending'},
    {'min_score': -1}, {'max_score': 101}, {'min_score': 'nan'}, {'max_score': 'inf'},
    {'min_score': 90, 'max_score': 20}, {'sort_by': 'id'}, {'sort_dir': 'up'}, {'group_by': 'unknown'},
    {'limit': 0}, {'limit': 1001}, {'limit': 1.5}, {'format': 'pdf'}, {'user_id': ''}, {'indicator': ' '},
    {'department': ''}, {'start': 'bad'}, {'end': '9999-12-31'}, {'start': '2026-10-03', 'end': '2026-10-01'},
    {'end': '2026-10-02T12:00:00Z'},
])
def test_invalid_report_filters(report_env, params):
    client, _, analyst = report_env
    assert client.get('/api/reports/risk', headers=analyst, params=params).status_code == 422


@pytest.mark.parametrize('column', ['peak_score', 'start_time', 'user_id', 'department', 'category', 'status'])
@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_report_sort_and_limit(report_env, column, direction):
    full = report(report_env, {'sort_by': column, 'sort_dir': direction})
    ranks = {'category': ['Low', 'Medium', 'High', 'Critical'], 'status': ['open', 'under_investigation', 'closed']}
    values = [ranks[column].index(row[column]) if column in ranks else row[column] for row in full['alerts']]
    assert values == sorted(values, reverse=direction == 'desc')
    limited = report(report_env, {'sort_by': column, 'sort_dir': direction, 'limit': 2})
    assert limited['alerts'] == full['alerts'][:2]
    assert limited['summary']['total_alerts'] == 6


@pytest.mark.parametrize('group_by,expected', [('department', {'Finance': 4, 'IT': 2}), ('user', {'u1': 3, 'u2': 2, 'u3': 1}), ('indicator', {'download': 3, 'decoy': 2, 'denied': 1, 'No indicator': 1}), ('category', {'Low': 1, 'Medium': 2, 'High': 2, 'Critical': 1}), ('day', {'2026-10-01': 1, '2026-10-02': 3, '2026-10-03': 1, '2026-10-04': 1})])
def test_report_grouping(report_env, group_by, expected):
    result = report(report_env, {'group_by': group_by, 'limit': 1})
    assert {group['key']: group['count'] for group in result['groups']} == expected
    assert all(0 <= group['avg_score'] <= group['max_score'] for group in result['groups'])


def test_summary_compatibility_metadata_and_audit(report_env):
    result = report(report_env)
    assert {'coverage', 'alerts_by_category', 'alerts', 'disclaimer', 'generated_at', 'filters'} <= set(result)
    assert 'groups' not in result
    summary = result['summary']
    assert summary['total_alerts'] == 6 and summary['avg_peak_score'] == 64.17 and summary['max_peak_score'] == 95
    assert summary['open_count'] == 2 and summary['closed_count'] == 2
    assert summary['alerts_by_department'] == {'Finance': 4, 'IT': 2}
    assert summary['top_users'][0] == {'user_id': 'u1', 'count': 3, 'max_score': 80}
    assert summary['top_indicators'][0] == {'name': 'download', 'count': 3}
    client, admin, analyst = report_env
    assert client.get('/api/reports/range', headers=analyst).json() == result['data_range']
    assert client.get('/api/reports/indicators', headers=analyst).json() == ['decoy', 'denied', 'download']
    assert client.get('/api/reports/indicators').status_code == 401
    entry = next(item for item in client.get('/api/audit', headers=admin).json() if item['action'] == 'generate_report')
    assert entry['detail']['filters'] == result['filters']


def test_csv_matches_json_filters_order_limit_and_dated_filename(report_env):
    client, _, analyst = report_env
    params = {'start': '2026-10-02', 'end': '2026-10-04', 'department': 'Finance', 'category': 'High,Medium', 'status': 'open,closed', 'min_score': 50, 'max_score': 90, 'indicator': 'download', 'sort_by': 'category', 'sort_dir': 'asc', 'limit': 1, 'group_by': 'department'}
    expected = report(report_env, params)
    response = client.get('/api/reports/risk', headers=analyst, params={**params, 'format': 'csv'})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [int(row['alert_id']) for row in rows] == [row['alert_id'] for row in expected['alerts']]
    assert datetime.now(timezone.utc).date().isoformat() in response.headers['content-disposition']


def test_empty_report_preserves_coverage_summary_and_groups(report_env):
    result = report(report_env, {'start': '2035-01-01', 'end': '2035-01-02', 'group_by': 'department'})
    assert result['alerts'] == [] and result['groups'] == []
    assert result['summary']['total_alerts'] == 0
    assert result['summary']['avg_peak_score'] == result['summary']['max_peak_score'] == 0
    assert result['coverage']['events_analysed'] == result['coverage']['users_monitored'] == 0
