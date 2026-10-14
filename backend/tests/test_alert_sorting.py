from datetime import datetime, timedelta

import pytest

from app.models import Alert, Subject
from test_accounts import account_env


@pytest.fixture
def sort_env(account_env):
    client, admin, _, _, sessions = account_env
    rows = []
    with sessions() as db:
        for index in range(8):
            uid = f'user_{7 - index}'
            department = ['Finance', 'Engineering', 'Sales', 'HR'][index % 4]
            row = dict(id=index + 1, user_id=uid, department=department,
                       start_time=datetime(2026, 10, 1) + timedelta(hours=index % 3),
                       peak_score=[50, 80, 80, 50, 25, 95, 50, 80][index],
                       category=['High', 'Low', 'Critical', 'Medium'][index % 4],
                       status=['closed', 'open', 'under_investigation'][index % 3],
                       indicator_count=[3, 0, 2, 1, 4, 2, 1, 5][index])
            db.add(Subject(user_id=uid, department=department))
            db.add(Alert(id=row['id'], user_id=uid, start_time=row['start_time'], last_time=row['start_time'],
                         peak_score=row['peak_score'], category=row['category'], status=row['status'],
                         breakdown=[{'name': 'test', 'weight': 1}] * row['indicator_count']))
            rows.append(row)
        db.commit()
    return client, admin, sessions, rows


def ids(response):
    assert response.status_code == 200, response.text
    return [row['id'] for row in response.json()]


def value(row, column):
    if column == 'category':
        return ['Low', 'Medium', 'High', 'Critical'].index(row[column])
    if column == 'status':
        return ['open', 'under_investigation', 'closed'].index(row[column])
    return row[column]


def test_default_sort_preserves_risk_then_time_with_stable_id(sort_env):
    client, admin, _, rows = sort_env
    expected = sorted(rows, key=lambda row: row['id'])
    expected.sort(key=lambda row: row['start_time'], reverse=True)
    expected.sort(key=lambda row: row['peak_score'], reverse=True)
    assert ids(client.get('/api/alerts', headers=admin)) == [row['id'] for row in expected]


@pytest.mark.parametrize('column', ['id', 'user_id', 'department', 'start_time', 'peak_score', 'category', 'status', 'indicator_count'])
@pytest.mark.parametrize('direction', ['asc', 'desc'])
def test_all_columns_and_directions(sort_env, column, direction):
    client, admin, _, rows = sort_env
    expected = sorted(rows, key=lambda row: row['id'])
    expected.sort(key=lambda row: value(row, column), reverse=direction == 'desc')
    response = client.get('/api/alerts', headers=admin, params={'sort_by': column, 'sort_dir': direction, 'then_by': ''})
    assert ids(response) == [row['id'] for row in expected]


@pytest.mark.parametrize('primary,secondary', [('department', 'peak_score'), ('category', 'status'), ('indicator_count', 'start_time'), ('peak_score', 'indicator_count')])
def test_secondary_sort_and_final_tie_breaker(sort_env, primary, secondary):
    client, admin, _, rows = sort_env
    expected = sorted(rows, key=lambda row: row['id'])
    expected.sort(key=lambda row: value(row, secondary), reverse=True)
    expected.sort(key=lambda row: value(row, primary))
    response = client.get('/api/alerts', headers=admin, params={'sort_by': primary, 'sort_dir': 'asc', 'then_by': secondary, 'then_dir': 'desc'})
    assert ids(response) == [row['id'] for row in expected]


@pytest.mark.parametrize('params', [{'sort_by': 'invalid'}, {'then_by': 'invalid'}, {'sort_dir': 'sideways'}, {'then_dir': 'DESC'}, {'limit': 0}])
def test_invalid_sort_inputs(sort_env, params):
    client, admin, _, _ = sort_env
    assert client.get('/api/alerts', headers=admin, params=params).status_code == 422


@pytest.mark.parametrize('column', ['peak_score', 'indicator_count'])
def test_sort_precedes_limit_and_filters(sort_env, column):
    client, admin, sessions, _ = sort_env
    with sessions() as db:
        for index in range(205):
            timestamp = datetime(2026, 11, 1) + timedelta(minutes=index)
            db.add(Alert(user_id='user_7', start_time=timestamp, last_time=timestamp, peak_score=index,
                         category='Critical', status='open', breakdown=[{'name': 'test'}] * index))
        db.commit()
    response = client.get('/api/alerts', headers=admin, params={'sort_by': column, 'sort_dir': 'desc', 'then_by': '', 'status': 'open', 'category': 'Critical', 'department': 'Finance', 'limit': 2})
    assert response.status_code == 200
    assert [row['peak_score'] for row in response.json()] == [204, 203]
    default_limit = client.get('/api/alerts', headers=admin, params={'sort_by': column, 'sort_dir': 'asc', 'then_by': '', 'status': 'open', 'category': 'Critical', 'department': 'Finance'})
    assert len(default_limit.json()) == 200
    assert [row['peak_score'] for row in default_limit.json()[:2]] == [0, 1]
