"""Authentication (JWT + bcrypt) and role-based access control."""
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import AuditLog, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
ROLES = ("admin", "analyst")


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)
    return jwt.encode(
        {"sub": user.username, "role": user.role, "exp": expire},
        config.SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        username = payload.get("sub")
    except JWTError:
        raise err
    if not username:
        raise err
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise err
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return user

    return dep


require_admin = require_roles("admin")
require_staff = require_roles("admin", "analyst")


def audit(db: Session, user: User | str, action: str, target: str = "", detail: dict | None = None):
    """Append an entry to the audit log (REQ-10-01). Caller commits."""
    actor = user.username if isinstance(user, User) else str(user)
    role = user.role if isinstance(user, User) else None
    db.add(AuditLog(actor=actor, role=role, action=action, target=target, detail=detail or {}))
