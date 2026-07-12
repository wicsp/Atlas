from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import secrets
import time

from .config import AgentSettings, AuthSettings

HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "atlas_session"
SCOPED_TOKEN_PREFIX = "at2_"
SCOPED_TOKEN_BYTES = 32


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_token(token: str) -> str:
    return _b64encode(hashlib.sha256(token.encode("utf-8")).digest())


def generate_scoped_token() -> str:
    raw = secrets.token_bytes(SCOPED_TOKEN_BYTES)
    return SCOPED_TOKEN_PREFIX + _b64encode(raw)


def verify_scoped_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS)
    return f"{HASH_ALGORITHM}${HASH_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False
    if algorithm != HASH_ALGORITHM:
        return False

    try:
        salt = _b64decode(salt_text)
        expected_digest = _b64decode(digest_text)
    except (ValueError, base64.binascii.Error):
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def verify_login_password(password: str, auth: AuthSettings) -> bool:
    if auth.admin_password:
        return secrets.compare_digest(password, auth.admin_password)
    if auth.password_hash:
        return verify_password(password, auth.password_hash)
    return False


def verify_agent_token(token: str | None, agents: AgentSettings) -> bool:
    if not token or not agents.shared_token:
        return False
    return secrets.compare_digest(token, agents.shared_token)


def _sign_session(secret: str, issued_at: int) -> str:
    payload = str(issued_at).encode("ascii")
    return _b64encode(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest())


def create_session_token(secret: str, now: int | None = None) -> str:
    issued_at = int(now or time.time())
    signature = _sign_session(secret, issued_at)
    return f"{issued_at}.{signature}"


def verify_session_token(token: str | None, auth: AuthSettings, now: int | None = None) -> bool:
    if not token:
        return False
    try:
        issued_at_text, signature = token.split(".", 1)
        issued_at = int(issued_at_text)
    except ValueError:
        return False

    current_time = int(now or time.time())
    if issued_at > current_time + 30:
        return False
    if current_time - issued_at > auth.session_max_age_seconds:
        return False

    expected_signature = _sign_session(auth.session_secret, issued_at)
    return secrets.compare_digest(signature, expected_signature)


def print_password_hash() -> None:
    password = getpass.getpass("Password to hash: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    print(hash_password(password))
