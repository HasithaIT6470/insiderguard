"""Deterministic fictional 15-person demo. Reuses Gen primitives, not its seed."""
from datetime import date, datetime, timedelta, timezone

from .generator import DEPARTMENTS, FIELDS, HONEYTOKENS, Gen, _ts

PERSONAS = [
    ('u001', 'Nira Vale', 'Finance', 'Treasury Analyst', 'Honeytoken snooping', 'attack'),
    ('u002', 'Oren Fable', 'Finance', 'Ledger Analyst', 'Weekend after-hours collection', 'attack'),
    ('u003', 'Tavi Quill', 'Finance', 'Reporting Specialist', 'Approved month-end reporting spike', 'benign'),
    ('u004', 'Mira Venn', 'HR', 'People Operations Analyst', 'Credential attack followed by success', 'attack'),
    ('u005', 'Lio Fern', 'HR', 'Benefits Coordinator', 'One week of holiday without events', 'benign'),
    ('u006', 'Sera Wisp', 'HR', 'Policy Coordinator', 'Quiet regular policy work', 'benign'),
    ('u007', 'Arlo Flint', 'Engineering', 'Design Engineer', 'After-hours hoarding of restricted designs', 'attack'),
    ('u008', 'Ena Rook', 'Engineering', 'Software Engineer', 'Privilege probing, then a separate bulk incident', 'attack'),
    ('u009', 'Kian Moss', 'Engineering', 'Build Engineer', 'Approved large build-artifact downloads', 'benign'),
    ('u010', 'Vela Reed', 'Sales', 'Sales Operations Analyst', 'Bulk customer exfiltration, currently Critical', 'attack'),
    ('u011', 'Daro Pike', 'Sales', 'Account Operations Analyst', 'New-device customer export', 'attack'),
    ('u012', 'Fia Lark', 'Sales', 'Proposal Coordinator', 'Approved laptop replacement and file restore', 'benign'),
    ('u013', 'Noa Brim', 'IT', 'Infrastructure Analyst', 'Five-day low-and-slow exfiltration', 'attack'),
    ('u014', 'Zuri Cove', 'IT', 'On-call Systems Administrator', 'Legitimate scheduled night work', 'benign'),
    ('u015', 'Ivo Dawn', 'IT', 'Junior Support Engineer', 'New hire, pending baseline, legitimate large download', 'benign'),
]
SUPERVISORS = {
    'Finance': ('Runa Elm', 'finance.manager@example.com', '+1 202-555-0101'),
    'HR': ('Pavo Dell', 'hr.manager@example.com', '+1 202-555-0102'),
    'Engineering': ('Sola Finch', 'engineering.manager@example.com', '+1 202-555-0103'),
    'Sales': ('Teva Oak', 'sales.manager@example.com', '+1 202-555-0104'),
    'IT': ('Yaro Mist', 'it.manager@example.com', '+1 202-555-0105'),
}


def default_end(today=None):
    today = today or datetime.now(timezone.utc).date()
    return today - timedelta(days=(today.weekday() - 4) % 7)


class DemoGen(Gen):
    def __init__(self, seed=7, days=60, end=None):
        end = end or default_end()
        if not 45 <= days <= 120:
            raise ValueError('--days must be between 45 and 120 to preserve all story windows')
        if end > datetime.now(timezone.utc).date():
            raise ValueError('--end cannot be in the future')
        super().__init__(seed, 15, days, end - timedelta(days=days - 1))
        self.end = end
        self.people = {p[0]: p for p in PERSONAS}
        for user, persona in zip(self.users, PERSONAS):
            user.update(id=persona[0], dept=persona[2], device=f'LT-{persona[0].upper()}', device2=None,
                        login=9.0, access=40, downloads=3, power=False, oncall=False)
        # Every event on the final day is at 00:00 UTC: safe even when today is Friday.
        self.workdays = [d for d in self.workdays if d < end]
        self.holiday = {end - timedelta(days=k) for k in range(18, 25)}
        self.hire = end - timedelta(days=10)
        active_days = sum(1 for u in self.users for d in self.workdays if not (u['id'] == 'u015' and d < self.hire) and not (u['id'] == 'u005' and d in self.holiday))
        self.accesses = max(10, round(24000 / active_days) - 5)
        self.plan = {}

    def benign_day(self, u, d):
        uid = u['id']
        device = f'LT-REPLACEMENT-{uid.upper()}' if uid == 'u012' and d >= self.end - timedelta(days=25) else u['device']
        self.add(u, _ts(d, 9), 'auth', device=device)
        self.add(u, _ts(d, 13), 'auth', device=device)
        for _ in range(self.accesses + self.r.randint(-3, 3)):
            path, kind = self.res(u)
            self.add(u, _ts(d, self.r.uniform(9.2, 16.4)), 'file_access', path, kind, device)
        for hour in (10, 12, 15):
            kind = 'build_artifact' if uid == 'u009' else None
            path, kind = self.res(u, kind)
            volume = self.r.uniform(130, 180) if uid == 'u009' else self.r.uniform(6, 10)
            self.add(u, _ts(d, hour), 'download', path, kind, device, vol=volume)
        if uid == 'u014' and d.weekday() in (1, 3):
            self.add(u, _ts(d, 0), 'auth')
            path, kind = self.res(u, 'runbook')
            self.add(u, _ts(d, 0.1), 'file_access', path, kind)

    def remember(self, key, user, days, malicious, sid=None):
        self.plan[key] = {'user_id': user['id'], 'days': [d.isoformat() for d in days], 'malicious': malicious, 'scenario_id': sid}

    def build(self):
        for user in self.users:
            for day in self.workdays:
                if user['id'] == 'u015' and day < self.hire or user['id'] == 'u005' and day in self.holiday:
                    continue
                self.benign_day(user, day)
        users = {u['id']: u for u in self.users}
        def past(n): return max(self.end - timedelta(days=n), self.start + timedelta(days=18))
        scenarios = [
            ('honey', 'u001', [past(2)], 'honeytoken_snoop-01'),
            ('weekend', 'u002', [past((self.end.weekday() - 5) % 7 or 7)], 'weekend_hoarding-01'),
            ('credential', 'u004', [past(22)], 'credential_attack-01'),
            ('hoarding', 'u007', [past(32)], 'after_hours_hoarding-01'),
            ('probe', 'u008', [past(28)], 'privilege_probe-01'),
            ('repeat_bulk', 'u008', [past(15)], 'repeat_bulk_exfil-01'),
            ('bulk', 'u010', [past(1)], 'bulk_exfil-01'),
            ('device', 'u011', [past(3)], 'new_device_exfil-01'),
            ('slow', 'u013', [past(k) for k in range(19, 14, -1)], 'low_and_slow-01'),
        ]
        for key, uid, days, sid in scenarios:
            user = users[uid]
            for day in days:
                if key == 'honey':
                    # One registered decoy touch at a normal hour: exactly 50.
                    self.add(user, _ts(day, 11), 'file_access', HONEYTOKENS[0]['resource'], 'decoy', label=True, sid=sid, honey=True)
                elif key in ('weekend', 'hoarding'):
                    self.sc_after_hours(user, day, sid, big_file=key == 'hoarding')
                elif key == 'credential': self.sc_credential_attack(user, day, sid)
                elif key == 'probe': self.sc_priv_probe(user, day, sid)
                elif key in ('bulk', 'repeat_bulk'):
                    self.sc_bulk_exfil(user, day, sid)
                    self.add(user, _ts(day, 14.5), 'file_access', '/restricted/design_bundle', 'restricted', label=True, sid=sid)
                    if key == 'bulk': self.add(user, _ts(day, 14.55), 'device', device='USB-EXT-DEMO', label=True, sid=sid)
                elif key == 'device': self.sc_new_device(user, day, sid)
                elif key == 'slow': self.sc_low_and_slow(user, day, sid)
            self.remember(key, user, days, True, sid)
        # Noisy legitimate cases, all after learning. Resource types fit each job.
        monthends = [self.start + timedelta(days=k) for k in range(16, self.days - 1)
                     if (self.start + timedelta(days=k)).day >= 28]
        month = ([d for d in monthends if d <= past(8)] or monthends)[-1]
        self.remember('monthend', users['u003'], [month], False)
        for k in range(140):
            path, kind = self.res(users['u003'], 'finance_report')
            self.add(users['u003'], _ts(month, 14 + k / 1000), 'file_access', path, kind)
        path, kind = self.res(users['u003'], 'finance_report')
        self.add(users['u003'], _ts(month, 14.2), 'download', path, kind, vol=600)
        replacement = past(25)
        self.remember('replacement', users['u012'], [replacement], False)
        path, kind = self.res(users['u012'], 'proposal')
        self.add(users['u012'], _ts(replacement, 11), 'download', path, kind, device='LT-REPLACEMENT-U012', vol=600)
        for key, uid, day in [('build_old', 'u009', past(20)), ('build_recent', 'u009', past(2)), ('hire', 'u015', past(1))]:
            user = users[uid]
            self.remember(key, user, [day], False)
            path, kind = self.res(user, 'build_artifact' if uid == 'u009' else 'config_file')
            self.add(user, _ts(day, 14), 'download', path, kind, vol=700)
            if key == 'build_old':
                self.add(user, _ts(day, 14.1), 'device', device='WS-BUILD-U009')
        self.add(users['u014'], _ts(self.end, 0), 'auth')
        self.events.sort(key=lambda e: (e['timestamp'], e['user_id'], e['event_type'], str(e['resource'])))
        return self.events, self.plan


def generate_demo(seed=7, days=60, end=None):
    generator = DemoGen(seed, days, end)
    events, plan = generator.build()
    return events, HONEYTOKENS, plan
