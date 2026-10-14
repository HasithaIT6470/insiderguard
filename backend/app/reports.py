"""Filtered risk reports and dataset-relative report metadata."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Alert, Event, Subject, User, utcnow
from .pipeline import dataset_end
from .security import audit, require_staff

router = APIRouter()
CATEGORIES = ['Low', 'Medium', 'High', 'Critical']
STATUSES = ['open', 'under_investigation', 'closed']
FIELDS = ['alert_id', 'user_id', 'department', 'start_time', 'peak_score', 'category', 'status', 'indicators']


def data_range(db):
    first, last = db.scalar(select(func.min(Event.timestamp))), dataset_end(db)
    return {'first_event': first.isoformat() if first else None, 'last_event': last.isoformat() if last else None}


def names(alert):
    return {item['name'] for item in alert.breakdown or [] if item.get('name')}


def choices(value, allowed, label):
    if value is None:
        return []
    selected = list(dict.fromkeys(item.strip() for item in value.split(',')))
    if any(item not in allowed for item in selected):
        raise HTTPException(422, f"Invalid {label}; allowed values: {', '.join(allowed)}")
    return selected


@router.get('/reports/range')
def report_range(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return data_range(db)


@router.get('/reports/indicators')
def report_indicators(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return sorted({item['name'] for breakdown in db.scalars(select(Alert.breakdown)) for item in breakdown or [] if item.get('name')})


@router.get('/reports/risk')
def risk_report(
    start: date | None = None, end: date | None = None,
    department: str | None = Query(None, min_length=1, max_length=64),
    category: str | None = None, status: str | None = None,
    min_score: float | None = Query(None, ge=0, le=100, allow_inf_nan=False),
    max_score: float | None = Query(None, ge=0, le=100, allow_inf_nan=False),
    user_id: str | None = Query(None, min_length=1, max_length=64),
    indicator: str | None = Query(None, min_length=1, max_length=128),
    sort_by: Literal['peak_score', 'start_time', 'user_id', 'department', 'category', 'status'] = 'peak_score',
    sort_dir: Literal['asc', 'desc'] = 'desc', limit: int = Query(1000, ge=1, le=1000),
    group_by: Literal['none', 'department', 'user', 'indicator', 'category', 'day'] = 'none',
    format: Literal['json', 'csv'] = 'json', db: Session = Depends(get_db), user: User = Depends(require_staff),
):
    categories, statuses = choices(category, CATEGORIES, 'category'), choices(status, STATUSES, 'status')
    if start and end and start > end:
        raise HTTPException(422, 'From date is after To date')
    if end == date.max:
        raise HTTPException(422, 'To date must be before 9999-12-31')
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(422, 'Minimum score must not exceed maximum score')
    if any(value is not None and not value.strip() for value in [department, user_id, indicator]):
        raise HTTPException(422, 'Department, user ID and indicator cannot be blank')
    lower = datetime.combine(start, time.min) if start else None
    upper = datetime.combine(end + timedelta(days=1), time.min) if end else None
    query = select(Alert, Subject.department).join(Subject, Subject.user_id == Alert.user_id)
    event_query = select(func.count()).select_from(Event)
    subject_query = select(Subject)
    if lower:
        query = query.where(Alert.start_time >= lower)
        event_query = event_query.where(Event.timestamp >= lower)
    if upper:
        query = query.where(Alert.start_time < upper)
        event_query = event_query.where(Event.timestamp < upper)
    if department:
        query = query.where(Subject.department == department)
        event_query = event_query.where(Event.department == department)
        subject_query = subject_query.where(Subject.department == department)
    if user_id:
        query = query.where(Alert.user_id == user_id)
        event_query = event_query.where(Event.user_id == user_id)
        subject_query = subject_query.where(Subject.user_id == user_id)
    if categories:
        query = query.where(Alert.category.in_(categories))
    if statuses:
        query = query.where(Alert.status.in_(statuses))
    if min_score is not None:
        query = query.where(Alert.peak_score >= min_score)
    if max_score is not None:
        query = query.where(Alert.peak_score <= max_score)
    columns = {'peak_score': Alert.peak_score, 'start_time': Alert.start_time, 'user_id': Alert.user_id,
               'department': Subject.department, 'category': case({value: rank for rank, value in enumerate(CATEGORIES)}, value=Alert.category, else_=-1),
               'status': case({value: rank for rank, value in enumerate(STATUSES)}, value=Alert.status, else_=-1)}
    column = columns[sort_by]
    matches = db.execute(query.order_by(column.asc() if sort_dir == 'asc' else column.desc(), Alert.id.asc())).all()
    if indicator:
        matches = [(alert, dept) for alert, dept in matches if indicator in names(alert)]
    filters = {'start': start.isoformat() if start else None, 'end': end.isoformat() if end else None,
               'department': department, 'category': ','.join(categories) if categories else None,
               'status': ','.join(statuses) if statuses else None, 'min_score': min_score, 'max_score': max_score,
               'user_id': user_id, 'indicator': indicator, 'sort_by': sort_by, 'sort_dir': sort_dir, 'limit': limit, 'group_by': group_by}
    rows = [{'alert_id': alert.id, 'user_id': alert.user_id, 'department': dept, 'start_time': alert.start_time.isoformat(),
             'peak_score': alert.peak_score, 'category': alert.category, 'status': alert.status,
             'indicators': '; '.join(f"{item['name']}({item.get('weight', 0):g})" for item in alert.breakdown or [])}
            for alert, dept in matches[:limit]]
    generated_at = utcnow()
    audit(db, user, 'generate_report', department or 'all', {'filters': filters, 'format': format, 'alerts': len(rows), 'total_alerts': len(matches)})
    db.commit()
    if format == 'csv':
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename=insiderguard_risk_report_{generated_at:%Y-%m-%d}.csv'})
    by_category, by_status, by_department, by_day, indicators = Counter(), Counter(), Counter(), Counter(), Counter()
    user_scores, groups = defaultdict(list), defaultdict(list)
    scores = []
    for alert, dept in matches:
        score = alert.peak_score
        scores.append(score)
        by_category[alert.category] += 1
        by_status[alert.status] += 1
        by_department[dept or 'Unassigned'] += 1
        day = alert.start_time.date().isoformat()
        by_day[day] += 1
        user_scores[alert.user_id].append(score)
        indicator_names = names(alert)
        indicators.update(indicator_names)
        if group_by != 'none':
            keys = indicator_names or {'No indicator'} if group_by == 'indicator' else [{
                'department': dept or 'Unassigned', 'user': alert.user_id, 'category': alert.category, 'day': day}[group_by]]
            for key in keys:
                groups[key].append(score)
    top_users = sorted([{'user_id': uid, 'count': len(values), 'max_score': max(values)} for uid, values in user_scores.items()], key=lambda row: (-row['count'], -row['max_score'], row['user_id']))[:5]
    subjects = list(db.scalars(subject_query.where(Subject.user_id.in_(event_query.with_only_columns(Event.user_id).distinct()))))
    payload = {'generated_at': generated_at.isoformat(), 'filters': filters,
               'coverage': {'events_analysed': db.scalar(event_query), 'users_monitored': len(subjects), 'baselines_established': sum(subject.baseline_status == 'established' for subject in subjects)},
               'alerts_by_category': dict(by_category), 'alerts': rows,
               'summary': {'total_alerts': len(matches), 'avg_peak_score': round(sum(scores) / len(scores), 2) if scores else 0,
                           'max_peak_score': max(scores, default=0), 'open_count': by_status['open'], 'closed_count': by_status['closed'],
                           'alerts_by_category': dict(by_category), 'alerts_by_status': dict(by_status), 'alerts_by_department': dict(by_department),
                           'top_users': top_users, 'top_indicators': [{'name': name, 'count': count} for name, count in sorted(indicators.items(), key=lambda row: (-row[1], row[0]))[:8]],
                           'alerts_by_day': dict(sorted(by_day.items()))},
               'summary_scope': 'all_matching_alerts', 'data_range': data_range(db),
               'disclaimer': 'Risk scores are investigative leads only and are not proof of malicious intent.'}
    if group_by != 'none':
        payload['groups'] = [{'key': key, 'count': len(values), 'avg_score': round(sum(values) / len(values), 2), 'max_score': max(values)} for key, values in sorted(groups.items())]
    return payload
