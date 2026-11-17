"""ASKAI central backend (HTTP/JSON API, Python standard library only).

Run:   python -m backend.main
Env:   see backend/settings.py and config/backend.example.env

Endpoints
  GET  /v1/health                         public liveness check
  POST /v1/enroll    {code,device_name,machine}  -> {client_id, token}
  POST /v1/ask       (Bearer client token)        -> {answer,...}
  GET  /v1/me        (Bearer client token)        -> usage + limits
  GET  /v1/providers (Bearer client token)        -> provider availability
  GET  /v1/admin/usage           (Bearer ADMIN token)
  GET  /v1/admin/models?provider=gemini   (ADMIN) live model list
  POST /v1/admin/chain {chain}   (ADMIN) change provider/model chain at runtime

Production: run behind HTTPS (Render / Fly.io / Cloud Run / Caddy all terminate
TLS for you) or give ASKAI_TLS_CERT + ASKAI_TLS_KEY to serve HTTPS directly.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import code_only, prompts
from .authentication import AuthError, Authenticator
from .db import Database
from .providers import FRIENDLY, ProviderError, Router, parse_chain
from .providers.base import redact, register_secrets
from .rate_limiter import LimitExceeded, RateLimiter
from .settings import Settings, load_settings
from .usage_tracking import UsageTracker

VERSION = "1.0.0"
log = logging.getLogger("askai.backend")


class App:
    """All backend logic, independent of the HTTP layer (easy to test)."""

    def __init__(self, settings: Settings, router: Router | None = None):
        self.s = settings
        self.db = Database(settings.db_path)
        self.auth = Authenticator(self.db, settings.admin_token, settings.max_failed_auth_per_ip)
        self.auth.open_enrollment = settings.open_enrollment
        self.auth.max_enroll_per_ip_hour = settings.max_enroll_per_ip_hour
        self.usage = UsageTracker(self.db)
        self.limiter = RateLimiter(settings, self.usage)
        chain = self.db.get_setting("chain") or settings.chain
        self.router = router or Router(settings.keys, chain, timeout=settings.provider_timeout)
        if router is not None and self.db.get_setting("chain"):
            self.router.chain = self.db.get_setting("chain")
        self._busy = threading.BoundedSemaphore(8)   # max parallel provider calls

    # ------------------------------------------------------------------ ask
    def validate_ask(self, body: dict) -> dict:
        mode = str(body.get("mode", "ASK")).upper()
        if mode not in prompts.MODES:
            raise ValueError(f"unknown mode {mode!r}")
        channel = body.get("channel", "dos")
        if channel not in prompts.CHANNEL:
            channel = "dos"
        question = str(body.get("question", ""))
        if len(question) > self.s.max_question_chars:
            raise ValueError(f"question too long (max {self.s.max_question_chars} characters)")
        files = body.get("files") or []
        if not isinstance(files, list) or len(files) > 3:
            raise ValueError("files must be a list of at most 3 files")
        total = 0
        clean_files = []
        for f in files:
            if not isinstance(f, dict):
                raise ValueError("bad file entry")
            content = str(f.get("content", ""))
            total += len(content)
            clean_files.append({"name": str(f.get("name", "FILE"))[:64],
                                "role": "log" if f.get("role") == "log" else "source",
                                "content": content})
        if total > self.s.max_file_chars:
            raise ValueError(f"files too large (max {self.s.max_file_chars} characters)")
        if not question.strip() and not clean_files:
            raise ValueError("empty question")
        history = []
        for h in (body.get("history") or [])[-self.s.max_history_turns * 2:]:
            if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
                history.append({"role": h["role"], "content": str(h.get("content", ""))[:6000]})
        while history and history[0]["role"] != "user":
            history.pop(0)
        prefer = None
        p = body.get("prefer")
        if isinstance(p, dict) and p.get("provider") and p.get("model"):
            prefer = (str(p["provider"]).lower(), str(p["model"]))
        return {"mode": mode, "channel": channel, "question": question,
                "files": clean_files, "history": history, "prefer": prefer}

    def ask(self, client, body: dict) -> dict:
        req = self.validate_ask(body)
        limits = self.limiter.check_and_reserve(client)
        prefer = req["prefer"] if client.can_select_model else None
        system = prompts.system_prompt(req["channel"])
        user_msg = prompts.build_user_message(req["mode"], req["question"], req["files"])
        messages = req["history"] + [{"role": "user", "content": user_msg}]
        t0 = time.time()
        try:
            with self._busy:
                res = self.router.chat(system, messages, max_tokens=self.s.max_output_tokens,
                                       prefer=prefer)
                checked = False
                modes = {m.strip().upper() for m in self.s.self_check_modes.split(",") if m.strip()}
                if req["mode"] in modes and not res.truncated:
                    try:
                        rev = self.router.chat(
                            system,
                            [{"role": "user", "content": prompts.SELF_CHECK.format(
                                question=user_msg, draft=res.text)}],
                            max_tokens=self.s.max_output_tokens, prefer=(res.provider, res.model))
                        if rev.text.strip() and not rev.truncated:
                            res.in_tokens += rev.in_tokens
                            res.out_tokens += rev.out_tokens
                            res.text = rev.text
                            checked = True
                    except ProviderError as e:
                        log.warning("self-check skipped: %s", e)
        except ProviderError as e:
            self.usage.record(client.id, mode=req["mode"], status="error:" + e.kind,
                              ms=int((time.time() - t0) * 1000),
                              error="; ".join(getattr(e, "details", [str(e)])))
            raise
        kind = "text"
        if req["mode"] in ("GENERATE", "SOLVE", "ASK"):
            pp = code_only.postprocess(res.text, strict=req["mode"] == "GENERATE")
            kind, res.text = pp["kind"], pp["text"]
        status = "truncated" if res.truncated else "ok"
        ms = int((time.time() - t0) * 1000)
        self.usage.record(client.id, mode=req["mode"], provider=res.provider, model=res.model,
                          status=status, in_tokens=res.in_tokens, out_tokens=res.out_tokens, ms=ms)
        log.info("ask client=%s mode=%s %s:%s %d ms in=%d out=%d", client.id, req["mode"],
                 res.provider, res.model, ms, res.in_tokens, res.out_tokens)
        lim = limits.as_dict()
        lim["used_today"] += 1
        lim["used_month"] += 1
        lim["left_today"] = max(0, lim["left_today"] - 1)
        lim["left_month"] = max(0, lim["left_month"] - 1)
        return {"ok": True, "answer": res.text, "kind": kind, "provider": res.provider, "model": res.model,
                "truncated": res.truncated, "self_checked": checked, "ms": ms, "limits": lim}

    def providers_info(self, client) -> dict:
        return {
            "configured": self.router.configured(),
            "chain": [f"{p}:{m}" for p, m in self.router.candidates()],
            "can_select_model": client.can_select_model,
        }

    def set_chain(self, chain: str) -> list[str]:
        parsed = parse_chain(chain)
        if not parsed:
            raise ValueError("chain must look like 'gemini:model,groq:model'")
        self.db.set_setting("chain", chain)
        self.router.chain = chain
        return [f"{p}:{m}" for p, m in parsed]


# ======================================================================
#  HTTP layer
# ======================================================================
def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ASKAI/" + VERSION
        sys_version = ""

        def log_message(self, fmt, *args):  # route to logging, no bodies
            log.debug("%s %s", self.address_string(), fmt % args)

        # ---------------------------------------------------- helpers
        def _ip(self) -> str:
            if app.s.trust_proxy:
                fwd = self.headers.get("X-Forwarded-For")
                if fwd:
                    return fwd.split(",")[0].strip()
            return self.client_address[0]

        def _send(self, status: int, payload: dict, headers: dict | None = None):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, kind: str, message: str, headers=None):
            self._send(status, {"ok": False, "error": {"kind": kind, "message": message}}, headers)

        def _body(self) -> dict | None:
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > app.s.max_request_bytes:
                if 0 < n <= 4_000_000:          # drain so the client sees our answer
                    self.rfile.read(n)
                self._error(413, "too_large", f"request too large (max {app.s.max_request_bytes} bytes)")
                self.close_connection = True
                return None
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
                return body
            except ValueError:
                self._error(400, "bad_request", "body must be a JSON object")
                return None

        def _client(self):
            try:
                return app.auth.authenticate(self.headers.get("Authorization"), self._ip())
            except AuthError as e:
                self._error(e.status, "unauthorized" if e.status != 429 else "blocked", str(e))
                return None

        def _admin(self) -> bool:
            if app.auth.is_admin(self.headers.get("Authorization"), self._ip()):
                return True
            self._error(403, "forbidden", "admin token required")
            return False

        # ---------------------------------------------------- routes
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/v1/health":
                return self._send(200, {"ok": True, "service": "askai", "version": VERSION,
                                        "providers": app.router.configured(),
                                        "open_enrollment": app.s.open_enrollment})
            if url.path == "/v1/me":
                c = self._client()
                if c:
                    self._send(200, {"ok": True, "client_id": c.id, "name": c.name,
                                     "limits": app.limiter.limits_for(c).as_dict()})
                return
            if url.path == "/v1/providers":
                c = self._client()
                if c:
                    self._send(200, {"ok": True, **app.providers_info(c)})
                return
            if url.path == "/v1/admin/usage":
                if self._admin():
                    self._send(200, {"ok": True, "usage": app.usage.summary()})
                return
            if url.path == "/v1/admin/models":
                if not self._admin():
                    return
                prov = parse_qs(url.query).get("provider", ["gemini"])[0]
                if prov not in app.router.keys:
                    return self._error(400, "bad_request", f"provider {prov} not configured")
                try:
                    return self._send(200, {"ok": True, "models": app.router.provider(prov).list_models()})
                except ProviderError as e:
                    return self._error(502, e.kind, str(e))
            self._error(404, "not_found", "unknown endpoint")

        def do_POST(self):
            path = urlparse(self.path).path
            # Always consume the (size-limited) body BEFORE answering anything:
            # closing a socket with unread request data makes Windows send a TCP
            # reset, so the client would see "connection aborted" instead of our
            # clear 401/403/404 message.
            body = self._body()
            if body is None:
                return
            if path == "/v1/enroll":
                try:
                    cid, token = app.auth.enroll(str(body.get("code", "")), str(body.get("device_name", "")),
                                                 str(body.get("machine", "")), self._ip())
                except AuthError as e:
                    return self._error(e.status, "unauthorized", str(e))
                log.info("enrolled new client %s", cid)
                return self._send(200, {"ok": True, "client_id": cid, "token": token})
            if path == "/v1/ask":
                c = self._client()
                if c is None:
                    return
                try:
                    return self._send(200, app.ask(c, body))
                except ValueError as e:
                    return self._error(400, "bad_request", str(e))
                except LimitExceeded as e:
                    return self._error(429, "limit", str(e), {"Retry-After": str(e.retry_after)})
                except ProviderError as e:
                    status = {"quota": 503, "rate": 503, "auth": 502, "timeout": 504}.get(e.kind, 502)
                    return self._error(status, "provider_" + e.kind, FRIENDLY.get(e.kind, str(e)))
                except Exception:  # never leak internals
                    log.exception("ask failed")
                    return self._error(500, "internal", "internal server error")
            if path == "/v1/admin/chain":
                if not self._admin():
                    return
                try:
                    return self._send(200, {"ok": True, "chain": app.set_chain(str(body.get("chain", "")))})
                except ValueError as e:
                    return self._error(400, "bad_request", str(e))
            self._error(404, "not_found", "unknown endpoint")

    return Handler


class _RedactFilter(logging.Filter):
    """Final safety net: no log record may contain a credential."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


def install_log_redaction(secrets) -> None:
    register_secrets(secrets)
    f = _RedactFilter()
    for h in logging.getLogger().handlers:
        h.addFilter(f)
    logging.getLogger().addFilter(f)


def serve(settings: Settings | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = settings or load_settings()
    install_log_redaction([*s.keys.values(), s.admin_token])
    app = App(s)
    if not any(s.keys.values()):
        log.warning("No provider API key configured - every /v1/ask will fail.")
    class Server(ThreadingHTTPServer):
        # Windows SO_REUSEADDR would let a 2nd instance share the port; forbid it
        allow_reuse_address = os.name != "nt"

        def server_bind(self):
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    httpd = Server((s.host, s.port), make_handler(app))
    scheme = "http"
    if s.tls_cert and s.tls_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(s.tls_cert, s.tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    log.info("ASKAI backend %s on %s://%s:%d  chain=%s", VERSION, scheme, s.host, s.port,
             [f"{p}:{m}" for p, m in app.router.candidates()])
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
    sys.exit(0)
