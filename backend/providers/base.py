"""Unified AI-provider interface (stdlib HTTP only, no vendor SDKs)."""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

# error kinds -> how the router reacts
#   auth         provider key invalid           -> skip provider
#   quota        free tier / credits exhausted  -> next candidate
#   rate         temporary rate limit (429)     -> retry later / next
#   unavailable  overloaded / 5xx / model gone  -> retry once / next
#   bad_request  our request rejected           -> next candidate
#   network      DNS / connection failure       -> retry once / next
#   timeout      no answer in time              -> next candidate
RETRYABLE = {"rate", "unavailable", "network"}

# anything that looks like a provider credential (also partially masked
# echoes such as "sk-proj-****abcd") is removed from errors and logs
_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])(sk-[A-Za-z0-9_*\-]{6,}|AIza[0-9A-Za-z_\-]{10,}|AQ\.[A-Za-z0-9_\-]{10,}|"
                     r"gsk_[A-Za-z0-9]{10,}|sk-or-[A-Za-z0-9\-]{10,}|askai_[A-Za-z0-9_\-]{10,}|"
                     r"Bearer\s+[A-Za-z0-9._\-]{10,})")
_EXTRA_SECRETS: list[str] = []


def register_secrets(values) -> None:
    """Exact secret values (provider keys, admin token) to redact as well."""
    _EXTRA_SECRETS.extend(v for v in values if v and len(v) >= 8)


def redact(text: str) -> str:
    text = str(text)
    for s in _EXTRA_SECRETS:
        text = text.replace(s, "[REDACTED]")
    return _KEY_RE.sub("[REDACTED]", text)


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, *, status: int = 0, retry_after: float = 0):
        message = redact(message)
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    in_tokens: int = 0
    out_tokens: int = 0
    truncated: bool = False


def http_json(method: str, url: str, headers: dict, body: dict | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {"raw": raw[:500].decode("utf-8", "replace")}
        payload["_retry_after"] = e.headers.get("Retry-After", "") if e.headers else ""
        return e.code, payload
    except (socket.timeout, TimeoutError) as e:
        raise ProviderError("timeout", f"provider did not answer within {timeout:.0f} s") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise ProviderError("timeout", f"provider did not answer within {timeout:.0f} s") from e
        raise ProviderError("network", f"cannot reach provider: {e.reason}") from e
    except (ConnectionError, OSError) as e:
        raise ProviderError("network", f"connection error: {e}") from e


def classify_status(status: int, message: str) -> str:
    m = message.lower()
    if status in (401,) or "api key not valid" in m or "invalid api key" in m or "api_key_invalid" in m:
        return "auth"
    if status == 403:
        return "auth"
    if status == 429:
        if any(w in m for w in ("quota", "credit", "billing", "exceeded your current", "insufficient")):
            return "quota"
        return "rate"
    if status == 402:
        return "quota"
    if status == 404:
        return "unavailable"     # model removed / not available for this key
    if status in (408, 504):
        return "timeout"
    if status >= 500:
        return "unavailable"
    return "bad_request"


def retry_after_of(payload: dict) -> float:
    try:
        return float(payload.get("_retry_after") or 0)
    except ValueError:
        return 0.0


class Provider:
    name = "base"

    def __init__(self, api_key: str, timeout: float = 90):
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, model: str, system: str, messages: list[dict], *,
             max_tokens: int, temperature: float = 0.2) -> ChatResult:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError
