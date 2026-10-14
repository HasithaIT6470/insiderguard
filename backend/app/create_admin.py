"""Bootstrap an administrator: python -m app.create_admin."""
from getpass import getpass
import re

from fastapi import HTTPException
from sqlalchemy import func, select

from .database import SessionLocal, init_db
from .models import User
from .security import audit, hash_password, validate_password


def main() -> int:
    try:
        username = getpass("Admin username: ").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            print("Username must be 3-64 letters, digits, underscores, periods or hyphens.")
            return 1
        password = getpass("Password: ")
        confirmation = getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.")
            return 1
        validate_password(password, username)
        init_db()
        with SessionLocal() as db:
            if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
                print("An account with this username already exists.")
                return 1
            db.add(User(username=username, role="admin", password_hash=hash_password(password, username)))
            audit(db, "bootstrap", "create_account", username, {"role": "admin"})
            db.commit()
        print(f"Administrator '{username}' created.")
        return 0
    except HTTPException as error:
        print(error.detail)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nAccount creation cancelled.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
