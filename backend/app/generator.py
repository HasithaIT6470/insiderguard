"""Labelled synthetic enterprise telemetry generator (no real data, no real credentials).

Usage:
    python -m app.generator --out events.csv            # write CSV (+ honeytokens.json)
    python -m app.generator --post http://localhost:8000 --user admin --password '...'
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta

DEPARTMENTS = {
    "Finance": ["finance_report", "ledger", "invoice"],
    "HR": ["hr_record", "policy_doc", "payroll_sheet"],
    "Engineering": ["source_code", "design_doc", "build_artifact"],
    "Sales": ["crm_record", "proposal", "price_list"],
    "IT": ["config_file", "log_archive", "runbook"],
}
RESTRICTED = ["/restricted/board_minutes_q{}.pdf", "/restricted/exec_compensation_{}.xlsx", "/restricted/m_and_a_pipeline_{}.docx"]
HONEYTOKENS = [
    {"resource": "/finance/decoy/payroll_master_2026.xlsx", "description": "Decoy payroll master file"},
    {"resource": "/it/decoy/domain_admin_credentials.txt", "description": "Decoy credential vault export"},
    {"resource": "/hr/decoy/termination_list_confidential.docx", "description": "Decoy HR list"},
    {"resource": "/engineering/decoy/prod_signing_keys.zip", "description": "Decoy signing key archive"},
]
FIELDS = ["timestamp", "user_id", "department", "event_type", "resource", "resource_type", "device_id",
          "result", "volume_mb", "honeytoken", "label_malicious", "scenario_id"]


def _ts(d: date, hour: float) -> datetime:
    return datetime.combine(d, datetime.min.time()) + timedelta(hours=hour)


class Gen:
    def __init__(self, seed: int, n_users: int, days: int, start: date):
        self.r = random.Random(seed)
        self.start, self.days = start, days
        self.workdays = [start + timedelta(days=i) for i in range(days) if (start + timedelta(days=i)).weekday() < 5]
        self.events: list[dict] = []
        self.users = []
        depts = list(DEPARTMENTS)
        for i in range(n_users):
            dept = depts[i % len(depts)]
            uid = f"u{i + 1:03d}"
            power = dept == "Engineering" and self.r.random() < 0.6
            self.users.append({
                "id": uid, "dept": dept, "device": f"LT-{uid.upper()}",
                "device2": f"WS-{uid.upper()}" if self.r.random() < 0.2 else None,
                "login": min(11.0, max(7.5, self.r.gauss(9.0, 0.8))),
                "access": self.r.randint(20, 50),
                "downloads": self.r.randint(2, 6),
                "dl_mu": 4.2 if power else 2.0,  # lognormal mu (MB): ~70MB median vs ~7MB
                "power": power,
                "oncall": self.r.random() < 0.1,
            })

    # ---------------------------------------------------------------- helpers
    def add(self, u, ts, etype, resource=None, rtype=None, device=None, result="success", vol=0.0,
            label=False, sid=None, honey=False):
        self.events.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"), "user_id": u["id"], "department": u["dept"],
            "event_type": etype, "resource": resource, "resource_type": rtype,
            "device_id": device or u["device"], "result": result, "volume_mb": round(vol, 2),
            "honeytoken": honey, "label_malicious": label, "scenario_id": sid,
        })

    def res(self, u, rtype=None):
        rtype = rtype or self.r.choice(DEPARTMENTS[u["dept"]] + ["general"])
        return f"/{u['dept'].lower()}/{rtype}/doc_{self.r.randint(1, 400)}.dat", rtype

    # ---------------------------------------------------------------- benign behaviour
    def benign_day(self, u, d):
        r = self.r
        start = u["login"] + r.gauss(0, 0.25)
        dev = u["device2"] if u["device2"] and r.random() < 0.3 else u["device"]
        if r.random() < 0.05:  # typo'd password
            for k in range(r.randint(1, 2)):
                self.add(u, _ts(d, start - 0.02 * (k + 1)), "auth", result="fail", device=dev)
        self.add(u, _ts(d, start), "auth", device=dev)
        if r.random() < 0.5:
            self.add(u, _ts(d, 13.0 + r.gauss(0, 0.2)), "auth", device=dev)
        n_acc = max(5, int(r.gauss(u["access"], u["access"] * 0.15)))
        if u["dept"] == "Finance" and d.day >= 28:  # month-end spike (benign)
            n_acc = int(n_acc * 2.2)
        for _ in range(n_acc):
            path, rt = self.res(u)
            self.add(u, _ts(d, start + r.uniform(0.1, 8.0)), "file_access", path, rt, dev)
        for _ in range(max(1, int(r.gauss(u["downloads"], 1)))):
            path, rt = self.res(u)
            vol = min(450.0, r.lognormvariate(u["dl_mu"], 0.6))
            self.add(u, _ts(d, start + r.uniform(0.5, 8.0)), "download", path, rt, dev, vol=vol)
        if u["power"] and r.random() < 0.08:  # legitimate large build/artefact pull (rule false-positive bait)
            path, rt = self.res(u, "build_artifact")
            self.add(u, _ts(d, start + r.uniform(1, 6)), "download", path, rt, dev, vol=r.uniform(520, 700))
        if r.random() < 0.1:
            self.add(u, _ts(d, start + r.uniform(1, 7)), "device", None, None, u["device"], vol=0)
        if r.random() < 0.03:  # benign single denied access
            self.add(u, _ts(d, start + r.uniform(1, 7)), "denied_access", RESTRICTED[0].format(r.randint(1, 4)),
                     "restricted", dev, result="denied")
        if u["oncall"] and r.random() < 0.15:  # on-call late login
            self.add(u, _ts(d, 22.5 + r.uniform(0, 0.5)), "auth", device=dev)
            for _ in range(r.randint(3, 8)):
                path, rt = self.res(u)
                self.add(u, _ts(d, 22.6 + r.uniform(0, 1.0)), "file_access", path, rt, dev)

    # ---------------------------------------------------------------- malicious scenarios
    def sc_bulk_exfil(self, u, d, sid):
        t0 = 14.0
        for _ in range(8):
            p, rt = self.res(u)
            self.add(u, _ts(d, t0 + self.r.uniform(0, 0.4)), "file_access", p, rt, label=True, sid=sid)
        for k in range(10):
            p, rt = self.res(u)
            vol = self.r.uniform(520, 900) if k < 3 else self.r.uniform(180, 300)
            self.add(u, _ts(d, t0 + 0.4 + k * 0.05), "download", p, rt, vol=vol, label=True, sid=sid)

    def sc_after_hours(self, u, d, sid, big_file: bool):
        t0 = 2.0 + self.r.uniform(0, 0.4)
        self.add(u, _ts(d, t0), "auth", label=True, sid=sid)
        for k in range(150):
            p, rt = self.res(u)
            self.add(u, _ts(d, t0 + 0.05 + k * 0.012), "file_access", p, rt, label=True, sid=sid)
        for k in range(2):
            self.add(u, _ts(d, t0 + 0.3 + 0.1 * k), "file_access",
                     RESTRICTED[k].format(k + 1), "restricted", label=True, sid=sid)
        if big_file:
            p, rt = self.res(u)
            self.add(u, _ts(d, t0 + 2.2), "download", p, rt, vol=550, label=True, sid=sid)
            for k in range(3):
                p, rt = self.res(u)
                self.add(u, _ts(d, t0 + 2.3 + 0.02 * k), "download", p, rt, vol=60, label=True, sid=sid)
        else:
            for k in range(5):
                p, rt = self.res(u)
                self.add(u, _ts(d, t0 + 2.2 + 0.02 * k), "download", p, rt, vol=110, label=True, sid=sid)

    def sc_credential_attack(self, u, d, sid):
        t0 = 3.5
        for k in range(12):
            self.add(u, _ts(d, t0 + k * 0.006), "auth", result="fail", label=True, sid=sid)
        self.add(u, _ts(d, t0 + 0.1), "auth", label=True, sid=sid)
        for k in range(5):
            self.add(u, _ts(d, t0 + 0.12 + k * 0.01), "denied_access", RESTRICTED[k % 3].format(k + 1),
                     "restricted", result="denied", label=True, sid=sid)
        for k in range(2):
            self.add(u, _ts(d, t0 + 0.3 + k * 0.01), "file_access", RESTRICTED[k].format(k + 5), "restricted",
                     label=True, sid=sid)

    def sc_honeytoken(self, u, d, sid):
        h = self.r.choice(HONEYTOKENS)
        for k in range(self.r.randint(1, 3)):
            self.add(u, _ts(d, 11.0 + k * 0.05), "file_access", h["resource"], "decoy", label=True, sid=sid, honey=True)

    def sc_low_and_slow(self, u, d, sid):
        """Per-event and daily volumes stay below the fixed rule thresholds."""
        for k in range(3):
            p, rt = self.res(u)
            self.add(u, _ts(d, 10.5 + k * 1.5), "download", p, rt, vol=self.r.uniform(120, 150), label=True, sid=sid)

    def sc_new_device(self, u, d, sid):
        dev = f"USB-EXT-{self.r.randint(1000, 9999)}"
        self.add(u, _ts(d, 16.0), "device", None, None, dev, label=True, sid=sid)
        for k in range(2):
            p, _ = self.res(u, "customer_export")
            self.add(u, _ts(d, 16.1 + 0.05 * k), "download", p, "customer_export", dev,
                     vol=self.r.uniform(230, 270), label=True, sid=sid)

    def sc_priv_probe(self, u, d, sid):
        for k in range(4):
            self.add(u, _ts(d, 15.0 + k * 0.03), "denied_access", RESTRICTED[k % 3].format(k + 1), "restricted",
                     result="denied", label=True, sid=sid)
        for k in range(3):
            self.add(u, _ts(d, 15.2 + k * 0.03), "file_access", RESTRICTED[k % 3].format(k + 7), "restricted",
                     label=True, sid=sid)

    # ---------------------------------------------------------------- build
    def build(self):
        plan = [("bulk_exfil", 3), ("after_hours_hoarding", 3), ("credential_attack", 2), ("honeytoken_snoop", 3),
                ("low_and_slow", 3), ("new_device_exfil", 3), ("privilege_probe", 3)]
        candidates = [u for u in self.users if not u["oncall"]]
        self.r.shuffle(candidates)
        # scenario days start after the 14-day learning window
        late = [d for d in self.workdays if (d - self.start).days >= 17]
        assignments, ground_truth = [], []
        # Round-robin over scenario types so small populations still see every type once.
        queue = [(typ, k) for k in range(1, 4) for typ, n in plan if k <= n]
        queue = queue[: max(len(self.users) * 2 // 3, 1)]
        for typ, k in queue:
            if True:
                u = candidates.pop()
                if typ == "low_and_slow":
                    while u["power"] and candidates:  # use a low-volume user so the pattern is anomalous
                        candidates.insert(0, u)
                        u = candidates.pop()
                    i = self.r.randint(0, len(late) - 4)
                    days = late[i: i + 4]
                else:
                    days = [self.r.choice(late)]
                assignments.append((typ, f"{typ}-{k:02d}", u, days))
                ground_truth.append({"scenario_id": f"{typ}-{k:02d}", "user_id": u["id"],
                                     "days": [x.isoformat() for x in days]})
        scen_by_user_day = {(u["id"], d): (typ, sid, k_idx) for k_idx, (typ, sid, u, days) in enumerate(assignments)
                            for d in days}
        for u in self.users:
            for d in self.workdays:
                self.benign_day(u, d)
                item = scen_by_user_day.get((u["id"], d))
                if not item:
                    continue
                typ, sid, k_idx = item
                if typ == "bulk_exfil":
                    self.sc_bulk_exfil(u, d, sid)
                elif typ == "after_hours_hoarding":
                    self.sc_after_hours(u, d, sid, big_file=int(sid[-2:]) % 2 == 1)
                elif typ == "credential_attack":
                    self.sc_credential_attack(u, d, sid)
                elif typ == "honeytoken_snoop":
                    self.sc_honeytoken(u, d, sid)
                elif typ == "low_and_slow":
                    self.sc_low_and_slow(u, d, sid)
                elif typ == "new_device_exfil":
                    self.sc_new_device(u, d, sid)
                elif typ == "privilege_probe":
                    self.sc_priv_probe(u, d, sid)
        self.events.sort(key=lambda e: e["timestamp"])
        return self.events, ground_truth


def generate(seed: int = 42, n_users: int = 30, days: int = 49, start: date = date(2026, 8, 3)):
    """Return (events, honeytokens, ground_truth)."""
    events, truth = Gen(seed, n_users, days, start).build()
    return events, HONEYTOKENS, truth


def main():
    ap = argparse.ArgumentParser(description="InsiderGuard synthetic telemetry generator")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--days", type=int, default=49)
    ap.add_argument("--out", default="synthetic_events.csv")
    ap.add_argument("--post", help="Base URL of a running InsiderGuard API to ingest into")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password")
    args = ap.parse_args()

    events, honeytokens, truth = generate(args.seed, args.users, args.days)
    if args.post:
        import httpx

        if not args.password:
            raise SystemExit("--password required with --post")
        base = args.post.rstrip("/")
        tok = httpx.post(f"{base}/api/auth/login", data={"username": args.user, "password": args.password}).json()
        headers = {"Authorization": f"Bearer {tok['access_token']}"}
        for h in honeytokens:
            httpx.post(f"{base}/api/honeytokens", json=h, headers=headers)
        for i in range(0, len(events), 5000):
            r = httpx.post(f"{base}/api/events", json={"events": events[i: i + 5000]}, headers=headers, timeout=600)
            print(i, r.status_code, r.json().get("accepted"))
    else:
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(events)
        with open(args.out.rsplit(".", 1)[0] + "_honeytokens.json", "w") as fh:
            json.dump(honeytokens, fh, indent=2)
        with open(args.out.rsplit(".", 1)[0] + "_ground_truth.json", "w") as fh:
            json.dump(truth, fh, indent=2)
        print(f"wrote {len(events)} events, {len(truth)} labelled scenarios -> {args.out}")


if __name__ == "__main__":
    main()
