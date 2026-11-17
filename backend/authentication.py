"""Client authentication.

* Each installed computer gets its OWN random token (never the provider key).
* Only SHA-256 hashes of tokens and enrollment codes are stored.
* Devices obtain a token by enrolling with a limited-use, expiring,
  revocable enrollment code created by the administrator, or the admin
  creates a token directly (`python -m backend.admin create-client`).
* Failed authentications are counted per IP; an IP that fails too often
  is blocked for 15 minutes (brute-force / abuse protection).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from .db import Database

TOKEN_PREFIX = "askai_"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class Client:
    id: str
    name: str
    disabled: bool
    can_select_model: bool
    per_minute: int | None
    per_day: int | None
    per_month: int | None


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


class Authenticator:
    BLOCK_SECONDS = 15 * 60

    def __init__(self, db: Database, admin_token: str, max_failed_per_ip: int = 20):
        self.db = db
        self.admin_token = admin_token
        self.max_failed = max_failed_per_ip
        self._fails: dict[str, list[float]] = {}
        self._enrolls: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        # open enrollment: devices register WITHOUT a code (each still gets its
        # own token + limits); new registrations per IP are throttled
        self.open_enrollment = False
        self.max_enroll_per_ip_hour = 10

    # ------------------------------------------------------------ blocking
    def _check_ip(self, ip: str) -> None:
        with self._lock:
            now = time.time()
            hits = [t for t in self._fails.get(ip, []) if now - t < self.BLOCK_SECONDS]
            self._fails[ip] = hits
            if len(hits) >= self.max_failed:
                raise AuthError("Too many failed attempts from this address. Try again later.", 429)

    def _fail(self, ip: str) -> None:
        with self._lock:
            self._fails.setdefault(ip, []).append(time.time())

    # ------------------------------------------------------------- clients
    def create_client(self, name: str, *, can_select_model: bool = False,
                      enrolled_with: str | None = None, machine: str | None = None) -> tuple[str, str]:
        client_id = "c_" + secrets.token_hex(6)
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO clients(id,name,token_hash,created_at,can_select_model,enrolled_with,machine) "
            "VALUES(?,?,?,?,?,?,?)",
            (client_id, name[:80], _hash(token), int(time.time()), int(can_select_model),
             enrolled_with, (machine or "")[:120]),
        )
        return client_id, token

    def authenticate(self, auth_header: str | None, ip: str) -> Client:
        self._check_ip(ip)
        if not auth_header or not auth_header.startswith("Bearer "):
            self._fail(ip)
            raise AuthError("Missing client token. Install/enroll ASKAI on this computer first.")
        token = auth_header[7:].strip()
        row = self.db.one("SELECT * FROM clients WHERE token_hash=?", (_hash(token),))
        if row is None:
            self._fail(ip)
            raise AuthError("Unknown or revoked client token. Re-run the ASKAI setup to enroll again.")
        if row["disabled"]:
            raise AuthError("This ASKAI client has been disabled by the administrator.", 403)
        self.db.execute("UPDATE clients SET last_seen=? WHERE id=?", (int(time.time()), row["id"]))
        return Client(row["id"], row["name"], bool(row["disabled"]), bool(row["can_select_model"]),
                      row["per_minute"], row["per_day"], row["per_month"])

    def is_admin(self, auth_header: str | None, ip: str) -> bool:
        self._check_ip(ip)
        if not self.admin_token or not auth_header or not auth_header.startswith("Bearer "):
            return False
        ok = hmac.compare_digest(auth_header[7:].strip(), self.admin_token)
        if not ok:
            self._fail(ip)
        return ok

    # --------------------------------------------------------- enrollment
    def create_enroll_code(self, label: str, max_uses: int = 30, days_valid: int = 30) -> str:
        code = "ENR-" + secrets.token_urlsafe(12)
        expires = int(time.time()) + days_valid * 86400 if days_valid > 0 else None
        self.db.execute(
            "INSERT INTO enroll_codes(code_hash,label,max_uses,expires_at,created_at) VALUES(?,?,?,?,?)",
            (_hash(code), label[:80], max_uses, expires, int(time.time())),
        )
        return code

    def enroll(self, code: str, device_name: str, machine: str, ip: str) -> tuple[str, str]:
        self._check_ip(ip)
        if not (code or "").strip():
            if not self.open_enrollment:
                raise AuthError("An enrollment code is required by this ASKAI server.", 403)
            with self._lock:
                now_f = time.time()
                recent = [t for t in self._enrolls.get(ip, []) if now_f - t < 3600]
                if len(recent) >= self.max_enroll_per_ip_hour:
                    raise AuthError("Too many new registrations from this address. Try again later.", 429)
                recent.append(now_f)
                self._enrolls[ip] = recent
            name = (device_name or "device").strip()[:60] or "device"
            return self.create_client(name, enrolled_with="open", machine=machine)
        row = self.db.one("SELECT * FROM enroll_codes WHERE code_hash=?", (_hash(code or ""),))
        now = int(time.time())
        if row is None or row["disabled"]:
            self._fail(ip)
            raise AuthError("Invalid enrollment code.", 403)
        if row["expires_at"] and row["expires_at"] < now:
            raise AuthError("This enrollment code has expired. Ask the administrator for a new one.", 403)
        cur = self.db.execute(
            "UPDATE enroll_codes SET uses=uses+1 WHERE code_hash=? AND uses < max_uses",
            (row["code_hash"],),
        )
        if cur.rowcount != 1:
            raise AuthError("This enrollment code has reached its maximum number of installations.", 403)
        name = (device_name or "device").strip()[:60] or "device"
        return self.create_client(name, enrolled_with=row["label"], machine=machine)
