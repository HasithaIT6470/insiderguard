"""Load the labelled synthetic data set straight into the database and run the evaluation.

    python -m app.seed [--reset] [--seed 42]
"""
import argparse
import time

from sqlalchemy import select

from . import config
from .database import Base, SessionLocal, engine, init_db
from .evaluation import run_evaluation
from .generator import generate
from .models import Honeytoken, User
from .pipeline import ingest_records, reprocess_users, seed_rule_config
from .security import hash_password


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--days", type=int, default=49)
    args = ap.parse_args()

    if args.reset:
        from . import models  # noqa: F401

        Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        seed_rule_config(db)
        if config.ENV != "production" and db.scalar(select(User).limit(1)) is None:
            db.add(User(username=config.DEFAULT_ADMIN_USER, role="admin",
                        password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD, config.DEFAULT_ADMIN_USER)))
            db.add(User(username=config.DEFAULT_ANALYST_USER, role="analyst",
                        password_hash=hash_password(config.DEFAULT_ANALYST_PASSWORD, config.DEFAULT_ANALYST_USER)))
            db.commit()
        t0 = time.time()
        events, honeytokens, truth = generate(args.seed, args.users, args.days)
        print(f"generated {len(events)} events / {len(truth)} labelled scenarios in {time.time() - t0:.1f}s")
        for h in honeytokens:
            if not db.scalar(select(Honeytoken).where(Honeytoken.resource == h["resource"])):
                db.add(Honeytoken(resource=h["resource"], description=h["description"], created_by="seed"))
        db.commit()
        res = ingest_records(db, events, "seed")
        print(f"ingested accepted={res['accepted']} rejected={res['rejected']}")
        t0 = time.time()
        reprocess_users(db, silent=True)
        print(f"processed {len(res['affected_users'])} users in {time.time() - t0:.1f}s")
        ev = run_evaluation(db, run_by="seed")
        for mode, m in ev["modes"].items():
            print(f"{mode:13s} P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} "
                  f"FPR={m['false_positive_rate']:.3f} scenarios={m['scenarios_detected']}/{m['scenarios_total']} "
                  f"median_latency={m['median_detection_latency_minutes']}min")
    finally:
        db.close()


if __name__ == "__main__":
    main()
