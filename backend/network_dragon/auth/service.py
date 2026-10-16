import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from sqlalchemy import delete

from network_dragon.persistence.models import AuthSession, LoginLimit, User

hasher = PasswordHasher()
COOKIE = "dragon_session"


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def set_password(session, password: str):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Use a password of 12–256 characters")
    user = session.get(User, 1)
    if user:
        user.password_hash = hasher.hash(password)
    else:
        session.add(User(id=1, password_hash=hasher.hash(password)))
    session.execute(delete(AuthSession))


def verify(session, password):
    user = session.get(User, 1)
    try:
        return bool(user and hasher.verify(user.password_hash, password))
    except VerificationError:
        return False


def login(session, request, password):
    now = time.time()
    key = digest(request.client.host if request.client else "local")
    limit = session.get(LoginLimit, key)
    if limit and limit.expires > now and limit.count >= 5:
        return None, "rate_limited"
    if not limit:
        limit = LoginLimit(key=key, count=0, expires=now + 300)
        session.add(limit)
    if limit.expires <= now:
        limit.count, limit.expires = 0, now + 300
    if not verify(session, password):
        limit.count += 1
        return None, "invalid_credentials"
    limit.count = 0
    previous = request.cookies.get(COOKIE)
    if previous:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(previous)))
    token = secrets.token_urlsafe(32)
    auth = AuthSession(
        token_hash=digest(token), csrf=secrets.token_urlsafe(32), expires=now + 43200
    )
    session.add(auth)
    return (token, auth.csrf), None


def authenticate(session, request: Request):
    token = request.cookies.get(COOKIE, "")
    auth = session.get(AuthSession, digest(token)) if token else None
    if not auth or auth.expires < time.time():
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(auth.csrf, csrf):
            raise HTTPException(403, "CSRF token required")
    return auth
