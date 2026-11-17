"""Backend settings, read from environment variables (or an env file).

Provider API keys live ONLY here, on the server. They are never sent to
clients. Every value can be given as an environment variable; for local
use you may also point ASKAI_ENV_FILE at a KEY=VALUE file kept outside
any repository / synced folder.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)  # real env vars win


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Default provider/model chain. Tried in order; entries whose provider has
# no API key are skipped. Free-tier model availability changes often, so
# this is only a default: set ASKAI_CHAIN on the server (no client rebuild),
# or change it at runtime with `python -m backend.admin set-chain ...`.
DEFAULT_CHAIN = (
    "gemini:gemini-3.5-flash,"
    "gemini:gemini-flash-latest,"
    "gemini:gemini-flash-lite-latest,"
    "groq:llama-3.3-70b-versatile,"
    "openrouter:openrouter/free,"
    "openai:gpt-4.1-mini"
)


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8787
    tls_cert: str = ""
    tls_key: str = ""
    db_path: str = "askai_backend.sqlite3"
    admin_token: str = ""

    keys: dict = field(default_factory=dict)
    chain: str = DEFAULT_CHAIN

    max_request_bytes: int = 96_000
    max_question_chars: int = 8_000
    max_file_chars: int = 40_000
    max_history_turns: int = 6
    max_output_tokens: int = 32768   # Gemini counts its "thinking" in this limit
    provider_timeout: int = 90
    self_check_modes: str = "TRACE,REGS"

    # default per-client limits (can be overridden per client by admin)
    limit_per_minute: int = 15   # generation + TASM/run checks use several calls
    limit_per_day: int = 120
    limit_per_month: int = 2000
    # global safety net against spending / quota exhaustion
    global_per_day: int = 3000
    # enrollment / brute-force protection
    max_failed_auth_per_ip: int = 20
    # register devices without an enrollment code (still one token per device)
    open_enrollment: bool = False
    max_enroll_per_ip_hour: int = 10
    trust_proxy: bool = False


def load_settings() -> Settings:
    _load_env_file(os.environ.get("ASKAI_ENV_FILE"))
    s = Settings()
    s.host = _env("ASKAI_HOST", default=s.host)
    s.port = int(_env("PORT", "ASKAI_PORT", default=str(s.port)))
    s.tls_cert = _env("ASKAI_TLS_CERT")
    s.tls_key = _env("ASKAI_TLS_KEY")
    s.db_path = _env("ASKAI_DB", default=s.db_path)
    s.admin_token = _env("ASKAI_ADMIN_TOKEN")
    s.keys = {
        "gemini": _env("ASKAI_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "groq": _env("ASKAI_GROQ_API_KEY", "GROQ_API_KEY"),
        "openrouter": _env("ASKAI_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        "openai": _env("ASKAI_OPENAI_API_KEY", "OPENAI_API_KEY"),
    }
    s.chain = _env("ASKAI_CHAIN", default=s.chain)
    s.max_request_bytes = _int("ASKAI_MAX_REQUEST_BYTES", s.max_request_bytes)
    s.max_question_chars = _int("ASKAI_MAX_QUESTION_CHARS", s.max_question_chars)
    s.max_file_chars = _int("ASKAI_MAX_FILE_CHARS", s.max_file_chars)
    s.max_history_turns = _int("ASKAI_MAX_HISTORY_TURNS", s.max_history_turns)
    s.max_output_tokens = _int("ASKAI_MAX_OUTPUT_TOKENS", s.max_output_tokens)
    s.provider_timeout = _int("ASKAI_PROVIDER_TIMEOUT", s.provider_timeout)
    s.self_check_modes = _env("ASKAI_SELF_CHECK_MODES", default=s.self_check_modes)
    s.limit_per_minute = _int("ASKAI_LIMIT_PER_MINUTE", s.limit_per_minute)
    s.limit_per_day = _int("ASKAI_LIMIT_PER_DAY", s.limit_per_day)
    s.limit_per_month = _int("ASKAI_LIMIT_PER_MONTH", s.limit_per_month)
    s.global_per_day = _int("ASKAI_GLOBAL_PER_DAY", s.global_per_day)
    s.max_failed_auth_per_ip = _int("ASKAI_MAX_FAILED_AUTH", s.max_failed_auth_per_ip)
    s.trust_proxy = _env("ASKAI_TRUST_PROXY", default="0") in ("1", "true", "yes")
    s.open_enrollment = _env("ASKAI_OPEN_ENROLLMENT", default="0").lower() in ("1", "true", "yes")
    s.max_enroll_per_ip_hour = _int("ASKAI_MAX_ENROLL_PER_IP_HOUR", s.max_enroll_per_ip_hour)
    return s
