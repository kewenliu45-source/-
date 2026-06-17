"""Persistent user store for login and role management.

The current implementation uses a local JSON file so the app can support
managed users without introducing a database yet. The public functions here
are intentionally small so this module can be replaced by a database-backed
repository later.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from app.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    USER_PASSWORD,
    USER_USERNAME,
    USERS_FILE,
)

ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = {ROLE_ADMIN, ROLE_USER}

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 260_000
_SALT_BYTES = 16


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        _HASH_ITERATIONS,
    ).hex()
    return f"{_HASH_ALGORITHM}${_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = stored_hash.split("$", 3)
        iterations = int(iterations_text)
    except (ValueError, AttributeError):
        return False

    if algorithm != _HASH_ALGORITHM:
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected)


def _normalize_username(username: str) -> str:
    return username.strip()


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in VALID_ROLES:
        raise ValueError("invalid role")
    return normalized


def _user_record(username: str, password: str, role: str) -> dict[str, Any]:
    now = _now_iso()
    return {
        "username": _normalize_username(username),
        "role": _normalize_role(role),
        "password_hash": hash_password(password),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _seed_users() -> list[dict[str, Any]]:
    users = [_user_record(ADMIN_USERNAME, ADMIN_PASSWORD, ROLE_ADMIN)]
    if _normalize_username(USER_USERNAME) != _normalize_username(ADMIN_USERNAME):
        users.append(_user_record(USER_USERNAME, USER_PASSWORD, ROLE_USER))
    return users


def _write_users(users: list[dict[str, Any]]) -> None:
    directory = os.path.dirname(USERS_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    temp_file = f"{USERS_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump({"users": users}, file, ensure_ascii=False, indent=2)
    os.replace(temp_file, USERS_FILE)


def ensure_user_store() -> None:
    if os.path.exists(USERS_FILE):
        return
    _write_users(_seed_users())


def load_users(include_inactive: bool = True) -> list[dict[str, Any]]:
    ensure_user_store()
    with open(USERS_FILE, "r", encoding="utf-8") as file:
        payload = json.load(file)

    users = payload.get("users", [])
    if include_inactive:
        return users
    return [user for user in users if user.get("is_active", True)]


def list_users() -> list[dict[str, Any]]:
    return [
        {
            "username": user["username"],
            "role": user["role"],
            "is_active": user.get("is_active", True),
            "created_at": user.get("created_at", ""),
        }
        for user in load_users()
    ]


def find_user(username: str) -> dict[str, Any] | None:
    normalized = _normalize_username(username)
    for user in load_users():
        if hmac.compare_digest(user.get("username", ""), normalized):
            return user
    return None


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    user = find_user(username)
    if not user or not user.get("is_active", True):
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None
    return {"username": user["username"], "role": user["role"]}


def create_user(username: str, password: str, role: str) -> dict[str, Any]:
    normalized_username = _normalize_username(username)
    if not normalized_username:
        raise ValueError("username is required")
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")

    normalized_role = _normalize_role(role)
    users = load_users()
    for user in users:
        if hmac.compare_digest(user.get("username", ""), normalized_username):
            raise ValueError("username already exists")

    user = _user_record(normalized_username, password, normalized_role)
    users.append(user)
    _write_users(users)
    return {
        "username": user["username"],
        "role": user["role"],
        "is_active": user["is_active"],
        "created_at": user["created_at"],
    }


def _count_active_admins(users: list[dict[str, Any]]) -> int:
    return sum(
        1 for u in users
        if u.get("role") == ROLE_ADMIN and u.get("is_active", True)
    )


def update_user_role(username: str, role: str) -> None:
    normalized_username = _normalize_username(username)
    normalized_role = _normalize_role(role)
    users = load_users()

    for user in users:
        if hmac.compare_digest(user.get("username", ""), normalized_username):
            old_role = user.get("role")
            # 如果从 admin 改为非 admin，检查是否是最后一个 active admin
            if old_role == ROLE_ADMIN and normalized_role != ROLE_ADMIN:
                if _count_active_admins(users) <= 1:
                    raise ValueError("cannot change role: last active admin")
            user["role"] = normalized_role
            user["updated_at"] = _now_iso()
            _write_users(users)
            return

    raise ValueError("user not found")


def update_user_password(username: str, password: str) -> None:
    normalized_username = _normalize_username(username)
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")

    users = load_users()
    for user in users:
        if hmac.compare_digest(user.get("username", ""), normalized_username):
            user["password_hash"] = hash_password(password)
            user["updated_at"] = _now_iso()
            _write_users(users)
            return

    raise ValueError("user not found")


def set_user_active(username: str, is_active: bool) -> None:
    normalized_username = _normalize_username(username)
    users = load_users()

    for user in users:
        if hmac.compare_digest(user.get("username", ""), normalized_username):
            # 禁用时检查是否是最后一个 active admin
            if not is_active and user.get("role") == ROLE_ADMIN and user.get("is_active", True):
                if _count_active_admins(users) <= 1:
                    raise ValueError("cannot disable last active admin")
            user["is_active"] = is_active
            user["updated_at"] = _now_iso()
            _write_users(users)
            return

    raise ValueError("user not found")


def delete_user(username: str) -> None:
    normalized_username = _normalize_username(username)
    users = load_users()

    target = None
    for user in users:
        if hmac.compare_digest(user.get("username", ""), normalized_username):
            target = user
            break

    if target is None:
        raise ValueError("user not found")

    # 不允许删除最后一个 active admin
    if target.get("role") == ROLE_ADMIN and target.get("is_active", True):
        if _count_active_admins(users) <= 1:
            raise ValueError("cannot delete last active admin")

    users = [u for u in users if not hmac.compare_digest(u.get("username", ""), normalized_username)]
    _write_users(users)
