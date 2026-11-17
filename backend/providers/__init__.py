"""Provider registry + router with retries and fallback."""
from __future__ import annotations

import logging
import time

from .base import RETRYABLE, ChatResult, Provider, ProviderError
from .gemini import GeminiProvider
from .groq import GroqProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider

log = logging.getLogger("askai.providers")

PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
}

# user-facing explanation per final error kind
FRIENDLY = {
    "quota": "The AI provider's free quota / credits are exhausted. The administrator "
             "must wait for the quota to reset, add credits, or switch provider.",
    "rate": "The AI provider is rate-limiting requests right now. Wait a minute and try again.",
    "auth": "The server's AI provider key was rejected. The administrator must update it.",
    "unavailable": "The AI models are overloaded or unavailable right now. Try again shortly.",
    "network": "The server cannot reach the AI provider (network problem).",
    "timeout": "The AI provider took too long to answer. Try again or ask a shorter question.",
    "bad_request": "The AI provider rejected the request (maybe too long). Try a shorter question.",
    "none": "No AI provider is configured on the server.",
}


def parse_chain(chain: str) -> list[tuple[str, str]]:
    out = []
    for item in chain.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        prov, model = item.split(":", 1)
        prov, model = prov.strip().lower(), model.strip()
        if prov in PROVIDER_CLASSES and model:
            out.append((prov, model))
    return out


class Router:
    def __init__(self, keys: dict[str, str], chain: str, timeout: float = 90,
                 sleep=time.sleep):
        self.keys = {k: v for k, v in keys.items() if v}
        self.timeout = timeout
        self.chain = chain
        self._sleep = sleep
        self._providers: dict[str, Provider] = {}

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            self._providers[name] = PROVIDER_CLASSES[name](self.keys[name], self.timeout)
        return self._providers[name]

    def candidates(self, prefer: tuple[str, str] | None = None) -> list[tuple[str, str]]:
        cands = [c for c in parse_chain(self.chain) if c[0] in self.keys]
        if prefer and prefer[0] in self.keys:
            cands = [prefer] + [c for c in cands if c != prefer]
        return cands

    def configured(self) -> dict:
        return {name: bool(self.keys.get(name)) for name in PROVIDER_CLASSES}

    def chat(self, system: str, messages: list[dict], *, max_tokens: int,
             prefer: tuple[str, str] | None = None, temperature: float = 0.2) -> ChatResult:
        cands = self.candidates(prefer)
        if not cands:
            raise ProviderError("none", FRIENDLY["none"])
        errors: list[ProviderError] = []
        dead_providers: set[str] = set()
        for prov, model in cands:
            if prov in dead_providers:
                continue
            for attempt in range(2):
                try:
                    res = self.provider(prov).chat(model, system, messages,
                                                   max_tokens=max_tokens, temperature=temperature)
                    if errors:
                        log.info("answered by %s:%s after %d failure(s)", prov, model, len(errors))
                    return res
                except ProviderError as e:
                    log.warning("%s:%s attempt %d failed [%s] %s", prov, model, attempt + 1, e.kind, e)
                    errors.append(e)
                    if e.kind == "auth":          # key is bad for every model
                        dead_providers.add(prov)  # (quota is often per model)
                    if e.kind in RETRYABLE and attempt == 0 and e.status != 404:
                        self._sleep(min(max(e.retry_after, 1.5), 5))
                        continue
                    break
        # pick the most informative failure kind
        kinds = [e.kind for e in errors]
        for k in ("quota", "rate", "auth", "timeout", "network", "unavailable", "bad_request"):
            if k in kinds:
                final = ProviderError(k, FRIENDLY[k])
                final.details = [str(e) for e in errors]  # type: ignore[attr-defined]
                raise final
        raise ProviderError("unavailable", FRIENDLY["unavailable"])


__all__ = ["Router", "ProviderError", "ChatResult", "PROVIDER_CLASSES", "FRIENDLY", "parse_chain"]
