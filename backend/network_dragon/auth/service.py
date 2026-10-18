import hashlib
import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from network_dragon.persistence.models import ApiToken, Audit, AuthSession, LoginLimit, User

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


def bearer(request: Request):
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else None


def token_refusal(request: Request):
    """Bearer tokens are read-only and never touch sign-in, sign-out or password changes."""
    if bearer(request) is None or not request.url.path.startswith("/api/"):
        return None
    if request.url.path.startswith("/api/v1/session"):
        return "API tokens cannot manage sessions"
    if request.method not in {"GET", "HEAD"}:
        return "API tokens are read-only"
    return None


def api_token(session, raw: str):
    now = time.time()
    token = session.get(ApiToken, digest(raw)) if raw else None
    if not token or (token.expires_at is not None and token.expires_at <= now):
        return None
    if token.last_used_at is None or now - token.last_used_at >= 60:
        try:
            with session.get_bind().begin() as connection:
                connection.execute(
                    update(ApiToken)
                    .where(
                        ApiToken.token_hash == token.token_hash,
                        or_(ApiToken.last_used_at.is_(None), ApiToken.last_used_at <= now - 60),
                    )
                    .values(last_used_at=now)
                )
        except OperationalError:
            pass  # Usage stamps are best-effort; a busy writer never fails a read.
    return token


def create_token(session, name: str, expires_days: int | None = None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
        raise ValueError("Use a token name of 1–64 letters, digits, '.', '_' or '-'")
    if expires_days is not None and not 1 <= expires_days <= 3650:
        raise ValueError("Use --expires-days between 1 and 3650")
    if session.scalar(select(ApiToken.name).where(ApiToken.name == name)):
        raise ValueError(f"Token {name!r} already exists")
    raw, now = "nd_" + secrets.token_urlsafe(32), time.time()
    expires = now + expires_days * 86400 if expires_days else None
    session.add(ApiToken(token_hash=digest(raw), name=name, created_at=now, expires_at=expires))
    session.add(Audit(action="token.created", subject=name, facts={"expires_at": expires}))
    try:
        session.flush()
    except IntegrityError as exc:
        raise ValueError(f"Token {name!r} already exists") from exc
    return raw


def revoke_token(session, name: str):
    token = session.scalar(select(ApiToken).where(ApiToken.name == name))
    if not token:
        raise ValueError(f"No token named {name!r}")
    session.delete(token)
    session.add(Audit(action="token.revoked", subject=name))


def authenticate(session, request: Request):
    raw = bearer(request)
    if raw is not None:
        token = api_token(session, raw)
        if not token:
            raise HTTPException(
                401, "Invalid or expired API token", headers={"WWW-Authenticate": "Bearer"}
            )
        return token
    token = request.cookies.get(COOKIE, "")
    auth = session.get(AuthSession, digest(token)) if token else None
    if not auth or auth.expires < time.time():
        raise HTTPException(401, "Sign in to continue")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(auth.csrf, csrf):
            raise HTTPException(403, "CSRF token required")
    return auth
